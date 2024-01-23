# Switch Implementation

## CAM Table and VLANs

To implement the CAM table, we used a dictionary with the key being the pair ``(vlan_id, src_mac)``
and the value being the ``interface``. For trunk ports, we store the VLAN ID from which the packet came,
and for access ports, we store the VLAN ID associated with the port.

Upon the arrival of a packet, if it exists in the CAM table, we send the data to the corresponding interface.
If the destination is not known, we flood the packet to all ports in the current VLAN.
If it is a broadcast packet, we send the packet to all ports that are part of the current VLAN.

Using the function ``send_to_interface(interface_type, interface, data, length, next_interface, vlan_id)``,
we send the data to the appropriate interface, checking if there is a need to modify
the data (adding or removing the VLAN tag).

## Spanning Tree Protocol

If the destination address of the packet is ``01:80:c2:00:00:00``, then the packet is of type STP (Spanning Tree Protocol). In this case, we extract ``bdpu_root_bridge_id``, ``bdpu_sender_path_cost``, and ``bdpu_root_path_cost`` from the packet.

We apply the STP algorithm as presented in the assignment to determine whether the packet should be forwarded or not. If it is forwarded, we call ``the create_bdpu`` function to create a new STP packet that will be forwarded.

To keep track of the state of each port, we use the dictionary ``interface_state`` with the key being
``interface`` and the value being ``blocking`` or ``designated``.

## Running

```bash
sudo python3 test/topo.py
```

This will open 9 terminals, 6 hosts and 3 for the switches. On the switch terminal you will run 

```bash
make run_switch SWITCH_ID=X # X is 0,1 or 2
```

The hosts have the following IP addresses.
```
host0 192.168.1.1
host1 192.168.1.2
host2 192.168.1.3
host3 192.168.1.4
host4 192.168.1.5
host5 192.168.1.6
```

We will be testing using the ICMP. For example, from host0 we will run:

```
ping 192.168.1.2
```

