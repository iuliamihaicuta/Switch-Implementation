#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

is_root = True

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def create_bdpu(root_bridge_id, sender_bridge_id, sender_path_cost):
    data = b'\x01\x80\xC2\x00\x00\x00'
    data += get_switch_mac()
    data += int.to_bytes(23, 2, byteorder='big')
    data += bytes([42, 42, 3])
    # bpdu config
    data += int.to_bytes(int(root_bridge_id), 2, byteorder='big')
    data += int.to_bytes(int(sender_path_cost), 2, byteorder='big')
    data += int.to_bytes(int(sender_bridge_id), 2, byteorder='big')

    return data


def send_bdpu_every_sec(own_bridge_id, interfaces, interfaces_type):
    global is_root
    while True:
        # send BDPU on all trunk interfaces
        if is_root:
            for i in interfaces:
                if interfaces_type[i] == "T":
                    send_to_link(i, create_bdpu(own_bridge_id, own_bridge_id, 0), len(create_bdpu(own_bridge_id, own_bridge_id, 0)))
                    time.sleep(1)

def read_config_file(switch_id):
    file = open("configs/switch" + switch_id + ".cfg", "r")
    lines = file.readlines()

    interfaces_type = {}
    # read switch priority
    switch_priority = lines[0].split()[0]

    for i in range(1, len(lines)):
        line = lines[i].split()
        interface_type = line[1]
        # set interface type
        interfaces_type[i - 1] = interface_type

    return switch_priority, interfaces_type

def send_to_interface(interfaces_type, interface, data, length, next_interface, vlan_id, interface_state):
    # check if interface is in blocking state
    if interfaces_type[next_interface] == "T" and interface_state[next_interface] == "blocking":
        return

    # check if the frame is leaving the switch on the same type of interface
    if interfaces_type[interface] == interfaces_type[next_interface]:
        # send frame to interface
        send_to_link(next_interface, data, length)
    
    # check if the frame is leaving the switch on an access interface
    elif interfaces_type[interface] == "T" and int(interfaces_type[next_interface]) == int(vlan_id):
        # remove vlan tag
        data = data[0:12] + data[16:]
        length = length - 4

        # send frame to interface
        send_to_link(next_interface, data, length)

    # check if the frame is leaving the switch on a trunk interface
    elif interfaces_type[interface] != "T" and interfaces_type[next_interface] == "T":
        # add vlan tag
        
        data = data[0:12] + create_vlan_tag(int(interfaces_type[interface])) + data[12:]
        length = length + 4

        # send frame to interface
        send_to_link(next_interface, data, length)

def main():
    switch_id = sys.argv[1]

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)

    # read switch priority and interfaces type from config file
    switch_priority, interfaces_type = read_config_file(switch_id)

    # set interface state
    interface_state = {}

    # Set all trunk interfaces to be in blocking state
    for i in interfaces:
        if interfaces_type[i] == "T":
            interface_state[i] = "blocking"
            

    # set variables for root bridge
    own_bridge_id = switch_priority
    root_bridge_id = own_bridge_id
    root_path_cost = 0
    root_port = -1

    # set all trunk interfaces to be in designated state
    if own_bridge_id == root_bridge_id:
        for i in interfaces:
            if interfaces_type[i] == "T":
                interface_state[i] = "designated"


    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec, args=(own_bridge_id, interfaces, interfaces_type))
    t.start()


    # Implement a switch table as a dictionary
    macTable = {}
    
    global is_root
    
    while True:
        interface, data, length = recv_from_any_link()

        # Parse the Ethernet header
        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        # Print the MAC src and MAC dst in human readable format
        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # get vlan id from access interface
        if vlan_id == -1 and interfaces_type[interface] != "T":
            vlan_id = int(interfaces_type[interface])

        # add src_mac to macTable
        if vlan_id != -1:
            macTable[(vlan_id, src_mac)] = interface

        # broadcast frame if dest_mac is ff:ff:ff:ff:ff:ff
        if dest_mac == "ff:ff:ff:ff:ff:ff":
            for i in interfaces:
                if i != interface:
                    send_to_interface(interfaces_type, interface, data, length, i, vlan_id, interface_state)
        
        # check if BDPU
        elif dest_mac == "01:80:c2:00:00:00":
            # get root bridge id, sender bridge id and sender path cost from BDPU
            bdpu_root_bridge_id = int.from_bytes(data[17:19], byteorder='big')
            bdpu_sender_path_cost = int.from_bytes(data[19:21], byteorder='big')
            bdpu_sender_bridge_id = int.from_bytes(data[21:23], byteorder='big')

            # check if the bpdu root bridge id is smaller than the current root bridge id
            if bdpu_root_bridge_id < int(root_bridge_id):
                # set the new root bridge id
                root_bridge_id = bdpu_root_bridge_id
                root_path_cost = bdpu_sender_path_cost + 10
                root_port = interface

                # set all trunk interfaces to be in blocking state
                # except the root port if the switch was root
                if (is_root):
                    for i in interfaces:
                        if interfaces_type[i] == "T":
                            interface_state[i] = "blocking"
                    interface_state[root_port] = "designated"
                    is_root = False

                if (interface_state[root_port] == "blocking"):
                    interface_state[root_port] = "designated"

                # update bdpu and send it on all trunk interfaces
                for i in interfaces:
                    if interfaces_type[i] == "T":
                        send_to_link(i, create_bdpu(root_bridge_id, own_bridge_id, root_path_cost), len(create_bdpu(own_bridge_id, own_bridge_id, 0)))

            # check if the bpdu root bridge id is equal to the current root bridge id
            elif bdpu_root_bridge_id == int(root_bridge_id):
                # check if the bpdu sender path cost is smaller than the current root path cost
                if interface == root_port and bdpu_sender_path_cost + 10 < root_path_cost:
                    # add 10 to the path cost
                    root_path_cost = bdpu_sender_path_cost + 10

                    
                    for i in interfaces:
                        if interfaces_type[i] == "T":
                            send_to_link(i, create_bdpu(root_bridge_id, own_bridge_id, root_path_cost), len(create_bdpu(own_bridge_id, own_bridge_id, root_path_cost)))

                # chech if the port should be in designated state
                elif interface != root_port:
                    if bdpu_sender_path_cost > root_path_cost:
                        if interface_state[interface] != "designated":
                            interface_state[interface] = "designated"
                            send_to_link(interface, create_bdpu(root_bridge_id, own_bridge_id, root_path_cost), len(create_bdpu(own_bridge_id, own_bridge_id, root_path_cost)))

            # check if there is a cycle
            elif bdpu_sender_bridge_id == own_bridge_id:
                interface_state[interface] = "blocking"

            # if the switch is root, set all trunk interfaces to be in designated state
            if own_bridge_id == root_bridge_id:
                for i in interfaces:
                    if interfaces_type[i] == "T":
                        interface_state[i] = "designated"

        # check if dest_mac is in macTable
        elif (vlan_id, dest_mac) in macTable:
            send_to_interface(interfaces_type, interface, data, length, macTable[(vlan_id, dest_mac)], vlan_id, interface_state)

        # flood all interfaces except the one the frame was received on
        else:
            for i in interfaces:
                if i != interface:
                    send_to_interface(interfaces_type, interface, data, length, i, vlan_id, interface_state)

if __name__ == "__main__":
    main()
