#!/bin/bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 OpenAirInterface Software Alliance
# Demo traffic. The UPF only emits a usage report for a session whose volume
# changed, so a UE with no traffic shows nothing on the dashboard -- run this
# for both UEs before the demo.
#   ./traffic.sh start [seconds]   ./traffic.sh stop
DUR=${2:-3600}
case "${1:-start}" in
  start)
    for ue in ueransim-ue1:12.1.1.10:5000 ueransim-ue2:12.1.1.9:5201; do
      IFS=: read c ip port <<< "$ue"
      docker exec $c pkill -9 iperf3 2>/dev/null
      docker exec -d $c iperf3 -s -B $ip -p $port >/dev/null 2>&1
    done
    sleep 2
    docker exec oai-ext-dn pkill -9 iperf3 2>/dev/null; sleep 1
    docker exec -d oai-ext-dn iperf3 -t $DUR -c 12.1.1.10 -p 5000 >/dev/null 2>&1
    docker exec -d oai-ext-dn iperf3 -t $DUR -c 12.1.1.9  -p 5201 >/dev/null 2>&1
    echo "traffic started to both UEs for ${DUR}s; first usage report within 30 s"
    ;;
  stop)
    docker exec oai-ext-dn pkill -9 iperf3 2>/dev/null
    docker exec ueransim-ue1 pkill -9 iperf3 2>/dev/null
    docker exec ueransim-ue2 pkill -9 iperf3 2>/dev/null
    echo "traffic stopped"
    ;;
esac
