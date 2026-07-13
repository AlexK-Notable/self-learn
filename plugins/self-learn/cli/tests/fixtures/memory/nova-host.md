The Nova (HA host) runs on Wi-Fi; the ethernet interface is down by default.
A brief Wi-Fi drop loses DNS and all sockets for a minute or two, which looks
like the whole service died. It self-heals; the durable fix is wired ethernet
plus a DHCP reservation so the address stops moving.
