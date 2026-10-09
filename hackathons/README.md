# OpenAirInterface Hackathon 2026 North Carolina State University

Participants will build extensions across OAI RAN, UE, Core Network, and RIC
which can be useful for ISAC use cases. Teams will collect RAN/UE/Core telemetry, 
train or integrate lightweight AI models, and close the loop through RAN scheduling, 
power control, RIC xApps, or NWDAF/NEF-driven QoS adaptation. The goal is to understand 
how communication and sensing objectives interact across the full mobile network stack.

## Hackathon Infrastructure

Please refer to the [Infrastructure Guide](./infra.md) for detailed instructions on setting up
and using the hackathon infrastructure.

## Core Network for Hackathon

If you are using the hackathon infrastructure then you will be inside a pod. 
you will not be able to use container-in-container so you can't run OAI core network in 
containers. 

To run core network as a service follow [this tutorial](./core-network/README.md)

## Topic 1: RAN/GPU Offload

**Challenge**: Pick one of the following possible 
offloading tasks and implement it while running in RFsim:

- PBCH detection
- Symbol rotation and FFT

**Relation with ISAC**: ISAC depends on fast PHY processing 
of waveforms/channel features. Participants learn where sensing

[Long description](./ran-gpu-offload/README.md)

## Topic 2: RAN MAC/RRM

**Challenge**: Write a simple scheduler PRB policy that ensures a given 
percentage of resources is reserved for a given UE.

**Relation with ISAC**: ISAC is a resource tradeoff problem: 
spectrum/time/power must serve both data and sensing.

[Long description](./ran-mac-rrm/README.md)

## Topic 3: Real-Time RAN Control with dApps

**Challenge**: Create a policy for real-time PRB blocking control based on PHY-layer RF telemetry.

**Relation with ISAC**: Real-time RF sensing enables closed-loop RAN control decisions.

[Long description](./ran-control-dapps/README.md)

## Topic 4: FlexRIC Traffic Steering Use Case

**Challenge**: Write a RAN optimization policy for the UE handover management.
Monitor traffic load, compute policy and trigger a handover for a targeted UE.

**Relation with ISAC**: An observation xApp that monitors real-time traffic and triggers HO upon decision.

[Long description](./flexric-traffic-steering/README.md)

## Topic 5: Application Function (AF) managing QoS via NEF based on NWDAF

**Challenge**: Write an application function that can dynamically change QoS via the NEF based on metrics from the NWDAF.

**Relation with ISAC**: NWDAF, analytics and intelligence layer can be used for making predictions, and based on that, AF can take necessary actions.

[Long description](./af-qos-nef-nwdaf/README.md)

