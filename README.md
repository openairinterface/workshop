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

1. A laptop or remote server with minimum 4vCPU and 8GB of RAM and 4GB of storage. 
2. Make sure your laptop/remote server CPU supports `avx2` as it is needed by gNB/NR-UE containers. You can check via `lscpu | grep avx2`
3. Operating System: Ubuntu 22.04/24.04, RHEL 9/10, Fedora 40+, other linux based OS may work as well.  
4. **Note**: Apple M1/M2/M3 laptops and Windows Linux Subsystem (WSL) are not yet tested.

**Software Prerequisites**

|Software      |Version       |
|:-------------|:-------------|
|Docker engine |Minimum 25.04 |
|tshark        |Minimum 4.6.0 |
|wireshark     |Minimum 4.6.0 |

**Recommendation**: You can download terminal application terminator or similar application to open multiple terminals in the same screen. 

In case you do not have docker and wireshark you can download, 

:red-exclamation-mark: Make sure to select `yes` when the Wireshark installation asks you whether non-superusers should be able to capture packets.
Otherwise, you will have to run in sudo mode.

```bash
sudo add-apt-repository ppa:wireshark-dev/stable
sudo apt update
sudo apt install -y git net-tools wireshark

sudo apt install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu  $(lsb_release -cs)  stable"
sudo apt update
sudo apt install -y docker docker-ce
```

Add your username to the docker group, otherwise you will have to run in sudo mode. 
```bash
sudo usermod -a -G docker $(whoami)
```

Now, logout and login again. 

**To follow the hands-on tutorials:**

1. [Core Network Hands-on Tutorial](./cn/README.md)
2. [RAN Hands-on Tutorial](./ran/README.md)
3. [OAM Hands-on Tutorial](./oam/README.md)
