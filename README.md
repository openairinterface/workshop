<table style="border-collapse: collapse; border: none;">
  <tr style="border-collapse: collapse; border: none;">
    <td style="border-collapse: collapse; border: none;">
      <a href="http://www.openairinterface.org/">
         <img src="./cn/resources/oai_final_logo.png" alt="" border=3 height=50 width=150>
         </img>
      </a>
    </td>
    <td style="border-collapse: collapse; border: none; vertical-align: center;">
      <b><font size = "5">OpenAirInterface Training Material</font></b>
    </td>
  </tr>
</table>


Hello everyone, welcome to the home page of the hands-on tutorial. Here you will find all the information you need for the hands-on workshop. 

As a prerequisite you have to clone this repository: 

```bash
git clone https://gitlab.eurecom.fr/oai/trainings/oai-workshops.git
```

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

In case you do not have docker and wireshark you can download, 

```bash
sudo add-apt-repository ppa:wireshark-dev/stable
sudo apt update
sudo apt install -y git net-tools wireshark

sudo apt install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu  $(lsb_release -cs)  stable"
sudo apt update
sudo apt install -y docker docker-ce

# Add your username to the docker group, otherwise you will have to run in sudo mode.
sudo usermod -a -G docker $(whoami)

# login / logout

```

To follow the hands-on tutorial:

1. [Core Network Hands-on Tutorial](./cn/README.md)
2. [RAN Hands-on Tutorial](./ran/README.md)
3. [OAM Hands-on Tutorial](./oam/README.md)
