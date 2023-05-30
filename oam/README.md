# Overview

This tutorial describes the steps of deployment 5G OAI RAN, with integrated E2 agent, with FlexRIC, O-RAN compliant nearRT-RIC.

# 1. Installation

## 1.1 Install prerequisites

- A *recent* CMake (at least v3.15). 

  On Ubuntu, you might want to use [this PPA](https://apt.kitware.com/) to install an up-to-date version.

- SWIG (at least  v.4.0). 

  We use SWIG as an interface generator to enable the multi-language feature (i.e., C/C++ and Python) for the xApps. Please, check your SWIG version (i.e, `swig
  -version`) and install it from scratch if necessary as described here: https://swig.org/svn.html or via the code below: 
  
  ```bash
  git clone https://github.com/swig/swig.git
  cd swig
  ./autogen.sh
  ./configure --prefix=/usr/
  make
  make install
  ```

- Flatbuffer encoding(optional). 
  
  We also provide a flatbuffers encoding/decoding scheme as alternative to ASN.1. In case that you want to use it  follow the
  instructions at https://github.com/dvidelabs/flatcc and provide the path for the lib and include when selecting it at `ccmake ..` from the build directory 

## 1.2 Download the required dependencies. 

Below an example of how to install it in ubuntu
```bash
sudo apt install libsctp-dev python3.8 cmake-curses-gui libpcre2-dev python-dev
```

# 2. Deployment

## 2.1 OAI RAN

### 2.1.1 Clone the OAI repository
```bash
git clone https://gitlab.eurecom.fr/oai/openairinterface5g oai
cd oai/
git checkout e2_sub
```

### 2.1.2 Build OAI
```bash
cd cmake_targets/
./build_oai -I -w SIMU --gNB --nrUE -e2 --ninja
```

 * -I option is to install pre-requisites, you only need it the first time you build the softmodem or when some oai dependencies have changed.
 * -w option is to select the radio head support you want to include in your build. Radio head support is provided via a shared library, which is called the "oai device" The build script creates a soft link from liboai_device.so to the true device which will be used at run-time (here the USRP one, liboai_usrpdevif.so). The RF simulatorRF simulator is implemented as a specific device replacing RF hardware, it can be specifically built using -w SIMU option, but is also built during any softmodem build.
 * --gNB is to build the nr-softmodem and nr-cuup executables and all required shared libraries
 * --nrUE is to build the nr-uesoftmodem executable and all required shared libraries
 * --ninja is to use the ninja build tool, which speeds up compilation
 * -e2 option is to use the E2 agent, integrated within gNB.

## 2.2 FlexRIC

### 2.2.1 Clone the FlexRIC repository
```bash
git clone https://gitlab.eurecom.fr/mosaic5g/flexric flexric
cd flexric/
git checkout mir_dev
```

### 2.2.2 Build FlexRIC
```bash
mkdir build && cd build && cmake .. && make
```

### 2.2.3 Installation of Service Models (SMs)
```bash
sudo make install
```

By default the service model libraries will be installed in the path /usr/local/lib/flexric while the configuration file in `/usr/local/etc/flexric`.

 * Note: currently, only xApp KPM v03.00 and RC v01.03 (xapp_kpm_rc) is supported to communicate with the integrated E2 agent in OAI. If you are interested in custom SMs (MAC, RLC, PDCP, GTP, TC and SLICE), please follow the instructions at https://gitlab.eurecom.fr/mosaic5g/flexric.

# 3. Start the process

* start the gNB
```bash
cd oai/cmake_targets/ran_build/build
sudo ./nr-softmodem RFSIMULATOR=server -O ~/summerworkshop2023/oam/conf/gnb.sa.band78.fr1.106PRB.usrpb210.conf --gNBs.[0].min_rxtxtime 6 --rfsim --sa
```

* start the nrUE
```bash
cd oai/cmake_targets/ran_build/build
sudo RFSIMULATOR=127.0.0.1 ./nr-uesoftmodem -r 106 --numerology 1 --band 78 -C 3619200000 --nokrnmod --rfsim --sa --uicc0.imsi 001010000000001
```

* start the nearRT-RIC
```bash
cd flexric
./build/examples/ric/nearRT-RIC
```

* start the KPM+RC xApp
```bash
cd flexric
./build/examples/xApp/c/kpm_rc/xapp_kpm_rc
```
