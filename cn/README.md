<table style="border-collapse: collapse; border: none;">
  <tr style="border-collapse: collapse; border: none;">
    <td style="border-collapse: collapse; border: none;">
      <a href="http://www.openairinterface.org/">
         <img src="./resources/oai_final_logo.png" alt="" border=3 height=50 width=150>
         </img>
      </a>
    </td>
    <td style="border-collapse: collapse; border: none; vertical-align: center;">
      <b><font size = "5">OpenAirInterface 5G Core Network Workshop 2024</font></b>
    </td>
  </tr>
</table>


![SA Basic Demo](./resources/oaiworkshop.png)

The aim of this tutorial is to explain: 

1. How to configure OAI5G Core network
2. How it works end to end with a RF Simulated `oai-gnb` and `oai-nr-ue`
3. (Optional): Connect two UEs to the gNB in two different slices
4. (Optional): Configure a static ip-address for a UE in the UDR database

**Hardware Requirements**

1. A laptop or remote server with minimum 8vCPU and 16GB of RAM and 4GB of storage. Most of the CPU and RAM is consumed by OAI gNB and NR-UE RFSimulator. Core network requires minimum 2vCPU and 4GB RAM.
2. Make sure your laptop/remote server cpu supports `avx2`. You can check via `lscpu | grep avx2`
3. Operating System: Ubuntu 20.04 or 22.04. 
4. Note: macOS and new M1/M2 laptops are not yet tested and Windows Linux Subsystem (WSL) is not yet tested

**Software Prerequisites**

|Software      |Version                                       |
|:-------------|:---------------------------------------------|
|docker engine |Minimum 19.03.6                               |
|tshark        |Minimum 3.6.2 (Git v3.6.2 packaged as 3.6.2-2)|
|wireshark     |Minimum 3.6.2 (Git v3.6.2 packaged as 3.6.2-2)|

**NOTE**: 

1. If you are using docker engine version > 21 then `compose` command is included in `docker`. If you do not have docker installed [then follow the official link](https://docs.docker.com/engine/install/).
2. It is recommended to use a docker account when you are pulling images. On dockerhub there is a limit for `anonymous` pull request. Probably at the day of the workshop not everyone will be able to pull the images. So it is good if you pull images in advance.

**Reading time**: ~ 20mins

**Tutorial replication time**: ~ 60mins

**TABLE OF CONTENTS**

[[_TOC_]]

## 1. Creating the Environment

1. Create a folder where you can store all the result files of the tutorial and this repository

``` shell
cd
git clone https://gitlab.eurecom.fr/oai/trainings/oai-workshops.git .
git checkout main
git rebase origin/main
cd cn
```

2. Make sure you have either `docker compose` command or standalone `docker-compose` command. In case you want to install `docker-compose` standalone command then follow the below steps or this [link](https://docs.docker.com/compose/install/standalone/); if you installed `docker` using above steps, there is no need for `docker-compose`. You can then safely skip this step.

```bash
curl -SL https://github.com/docker/compose/releases/download/v2.26.0/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose
sudo ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

3. Pull all the container images which are required in this tutorial. In case you do not want to pull the images now `docker-compose` will pull the images for you.

```bash
##Recommended to login to your docker hub account
docker login
## Pull images 2024-june Core Network images
docker compose pull
  Pulling mysql              ... done
  Pulling oai-nrf            ... done
  Pulling oai-udr            ... done
  Pulling oai-udm            ... done
  Pulling oai-ausf           ... done
  Pulling oai-amf            ... done
  Pulling oai-smf            ... done
  Pulling oai-upf            ... done
  Pulling oai-traffic-server ... done
## Your choice if you want to pull develop images for RAN then you can use develop
docker pull oaisoftwarealliance/oai-nr-ue:2024.w26
docker pull oaisoftwarealliance/oai-gnb:2024.w26
```

4. (Optional) In case you do not have wireshark you can install 

```bash
sudo add-apt-repository ppa:wireshark-dev/stable
sudo apt update
sudo apt install wireshark
```

5. (Optional) if you want to run the gNB and core in different machines then you need some forwarding rules. 

```bash
sudo sysctl net.ipv4.conf.all.forwarding=1
sudo iptables -P FORWARD ACCEPT
# You also need to add a route in the gNB to access the core network
sudo ip route add route CORE_NETWORK_DOCKER_SUBNET via IP_ADDRESS_OF_CORE_NETWORK_HOST_MACHINE dev gNB_NIC_TOWARDS_CORE_NETWORK
```

## 2. Configuring the OAI-5G Core Network Functions

Since `v2.0.0` release of the 5G Core Network, the deployment files have been simplified:

1. The [docker compose](./docker-compose.yml) file has containers/images related parameters:
  * Which version of the images to use
  * Name and IP addresses of the containers
2. The [config.yaml](./conf/config.yaml) file has the real network configuration parameters such as:
  * PLMN / Slices
  * DNN
  * ...

## 3. Deploying OAI 5g Core Network

1. Create docker network interface so that we can capture initial packets to understand what happens when core network starts

```bash
cd ~/oai-workshops/cn
docker network create --driver=bridge --subnet=192.168.70.128/26 -o "com.docker.network.bridge.name"="oaiworkshop" oaiworkshop
```

or an easier way, just deploy the mysql database:

```bash
cd ~/oai-workshops/cn
docker compose -f docker-compose.yml up -d mysql
```

2. Run wireshark with `root` privileges select `oaiworkshop` interface.

(Optional) You can also capture packets using `tshark` command. 

```bash
sudo tshark -i oaiworkshop -f "sctp or port 80 or port 8080 or port 8805 or icmp or port 3306" -w /tmp/oaiworkshop.pcap
```

3. Start the core network (make sure you are in `~/oai-workshops/cn` folder)

```bash
cd ~/oai-workshops/cn
docker compose -f docker-compose.yml up -d
```

4. Wait for the core network to be healthy. You can check the core network state using

```bash
watch docker compose -f docker-compose.yml ps -a

Every 2,0s: docker compose -f docker-compose.yml ps -a

   Name                 Command                  State                       Ports
---------------------------------------------------------------------------------------------------
mysql        docker-entrypoint.sh mysqld      Up (healthy)   3306/tcp, 33060/tcp
oai-amf      /openair-amf/bin/oai_amf - ...   Up (healthy)   38412/sctp, 80/tcp, 8080/tcp, 9090/tcp
oai-ausf     /openair-ausf/bin/oai_ausf ...   Up (healthy)   80/tcp, 8080/tcp
oai-ext-dn   /bin/bash -c  ip route add ...   Up (healthy)
oai-nrf      /openair-nrf/bin/oai_nrf - ...   Up (healthy)   80/tcp, 8080/tcp, 9090/tcp
oai-smf      /openair-smf/bin/oai_smf - ...   Up (healthy)   80/tcp, 8080/tcp, 8805/udp
oai-udm      /openair-udm/bin/oai_udm - ...   Up (healthy)   80/tcp, 8080/tcp
oai-udr      /openair-udr/bin/oai_udr - ...   Up (healthy)   80/tcp, 8080/tcp
oai-upf      /openair-upf/bin/oai_upf - ...   Up (healthy)   2152/udp, 8805/udp
```

5. In this configuration of core network:

  - AMF subscribes to SMF registration event via NRF for SMF selection
  - SMF registers to NRF
  - SMF subscribes to UPF registration event via NRF for UPF discovery
  - UPF registers to NRF

We can check all these requests from the PCAPs or logs. 

6. PFCP heartbeat exchange between SMF and UPF

 - SMF and UPF exchange PFCP heartbeat messages

We can check these requests from the PCAPs or logs. 

## 4. Deploying OAI-GNB, RFSIM and UEs

In the [RAN workshop](../ran/README.md) you have learned how to use oai-gnb. Here we are using oai-gnb rfsimulator in a docker container. 

In case you want to use the bare-metal deployment without docker, please refer to the [RAN workshop](../ran/README.md).

### 4.1 Deploy OAI-GNB

Open three terminals and in one terminal type

```bash
docker logs oai-amf -f
```

Second terminal

```bash
docker logs oai-smf -f
```

Third terminal

```bash
docker compose -f docker-compose-ran.yml up -d oai-gnb
```

Wait for the gNB to be healthy and meanwhile you can check the logs of `oai-amf`.

### 4.2 Deploy OAI-NR-UE

Open a fourth terminal and start the UE.

```bash
docker compose -f docker-compose-ran.yml up -d oai-nr-ue
```

Check the logs of `oai-amf` and `oai-smf`. If the PDU session establishment is successful, the UE receives an IP address. 
This IP address (together with other PDU session information) is also logged to the console on SMF. 

However, this the best way to see if the UE got connected:

```bash
docker exec oai-nr-ue ifconfig
eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.70.150  netmask 255.255.255.192  broadcast 192.168.70.191

lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0

oaitun_ue1: flags=4305<UP,POINTOPOINT,RUNNING,NOARP,MULTICAST>  mtu 1500
        inet 10.0.0.2  netmask 255.255.255.0  destination 10.0.0.2
```

==> `10.0.0.2` has been allocated to the UE tunnel.

## 5. Traffic test

Now that we have an IP address and a successful PDU session, we perform traffic tests. 

Get inside the UE and try to ping `8.8.8.8` or `10.0.0.1` or `192.168.70.135`

```bash
docker exec -it oai-nr-ue bash
## ping towards internet
ping -I oaitun_ue1 8.8.8.8 -c4
## ping towards upf
ping -I oaitun_ue1 10.0.0.1 -c4
## ping towards oai-traffic-generator
ping -I oaitun_ue1 192.168.70.135 -c4
```

(optional) Connect the second UE and check `oai-amf` and `oai-smf` logs

```bash
docker compose -f docker-compose-ran.yml up -d oai-nr-ue2
```

```
$ docker exec oai-nr-ue2 ifconfig
eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.70.151  netmask 255.255.255.192  broadcast 192.168.70.191

lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0

oaitun_ue1: flags=4305<UP,POINTOPOINT,RUNNING,NOARP,MULTICAST>  mtu 1500
        inet 10.0.0.3  netmask 255.255.255.0  destination 10.0.0.3
```

```bash
docker exec -it oai-nr-ue2 bash
## ping towards internet
ping -I oaitun_ue1 8.8.8.8 -c4
## ping towards upf
ping -I oaitun_ue1 10.0.0.1 -c4
## ping towards oai-traffic-generator
ping -I oaitun_ue1 192.168.70.135 -c4
```

## 6. Analyse logs and PCAPs

Normally you will see below messages twice because we connected the 2 UEs and pinged 4 times for each UE.

Below messages are from AMF pcap

1. NGSetupRequest, NGSetupResponse
2. InitialUEMessage, Registration request, Registration request
3. DownlinkNASTransport, Identity request
4. UplinkNASTransport, Identity response
5. DownlinkNASTransport, Authentication request
6. UplinkNASTransport, Authentication response
7. DownlinkNASTransport, Security mode command
8. UplinkNASTransport, Security mode complete, Registration request
9. UERadioCapabilityInfoIndication
10. UplinkNASTransport, Registration complete
11. PDU session establishment request
12. PDUSessionResourceSetupRequest, DL NAS transport, PDU session establishment accept
13. PDUSessionResourceSetupResponse
14. UplinkNASTransport, UL NAS transport, PDU session release request (Regular deactivation)
15. PDUSessionResourceReleaseCommand, DL NAS transport, PDU session release command (Regular deactivation)
16. PDUSessionResourceReleaseResponse
17. UplinkNASTransport, UL NAS transport, PDU session release complete, UplinkNASTransport, Deregistration request (UE originating)
18. SHUTDOWN
19. SHUTDOWN ACK
20. SHUTDOWN_COMPLETE

## 7. Advanced Traffic Tests
Now that we have verified that the UE, gNB and CN behave as expected, we can do some advanced traffic tests.

We are using iperf3 to measure the bandwidth between the UE and the traffic-generator in the Core Network.

### 7.1 Install iperf3 in OAI NR UE
iperf3 is not installed per default in the OAI NR UE, so we need to install it:

```bash
docker exec -it oai-nr-ue bash
apt update
apt install iperf3
```

Then we star the iperf3 server on oai-ex-dn (in the core network) to test UPLINK direction.
```bash
docker exec -it oai-ext-dn iperf3 -s
```

Then, we connect to the iperf3 server from the UE
```bash
docker exec -it oai-nr-ue iperf3 -B 10.0.0.2 -c 192.168.70.135 
```

If we also want to test DOWNLINK direction, we can instruct iperf3 to do so using `-R`:

```bash
docker exec -it oai-nr-ue iperf3 -B 10.0.0.2 -c 192.168.70.135 -R
```

## 8. Remove all the docker containers

Make sure you are always in `summerworkshop2023/cn` folder

```bash
docker compose -f docker-compose-ran.yml down -t2 -v
docker compose -f docker-compose.yml down -t2 -v
```

## 9. Extra

1. If you want to see the resource consumption of `docker containers` you can use `docker stats`
2. If you want to see the processes running inside a container you can do `docker top`
