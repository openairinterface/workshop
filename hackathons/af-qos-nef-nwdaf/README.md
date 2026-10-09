# North Carolina State University Hackathon 2026 — Application Function (AF) managing QoS via NEF based on NWDAF

## Problem Statement

Dynamic QoS handling via subscribing to the NWDAF notifications and change the QoS through the NEF, on its own.

## Objective

Build an AF that closes the loop:

1. **Listen:** subscribe to NWDAF analytics through the NEF (for example
   *QoS Sustainability*: "tell me when this UE goes below 20 Mbit/s").
2. **Decide:** when a notification arrives, choose what to do.
3. **Act:** change the UE's QoS through the NEF (*AS Session with QoS*).
4. **Repeat:** when the problem is gone, go back to normal.

Your AF is an outside app. It talks **only to the NEF**, never directly to the
PCF or the NWDAF, the same way a real third-party app would.

## Prerequisites

**Knowledge**

* REST APIs, JSON and HTTP (`curl` is enough to start)
* Any programming language. Python with Flask or FastAPI is the easiest.
* Basic 5G ideas: UE, PDU session, QoS. No deep 3GPP knowledge needed.

**Software and hardware**

* A x86 (Intel/AMD) Linux machine with Docker and Docker Compose v2
* At least 4 CPU cores, 8 GB RAM and 10 GB free disk
* `curl`, `python3`
* You don't need GPU for this challenge

> The JupyterHub pods of the hackathon infrastructure cannot run containers.
> Run the setup below on a machine with Docker. Your AF code can run anywhere that can reach the NEF.

**Bonus points**: Use CAMARA API + OpenCAPIF

## Starting Point

* Repository: <https://github.com/openairinterface/workshop>, folder
  `hackathons/af-qos-nef-nwdaf`
* Configuration: everything is in [`manifests/`](manifests)
* Test environment: one Docker host running the 5G core, NWDAF, NEF and two
  simulated UEs (UERANSIM)

### What is running

```
                       Your AF  (outside app)
                          |  ^
          change QoS      |  |   notifications
     (AS Session with QoS)|  |   (analytics)
                          v  |
   +----------------------NEF------------------------------+
   |                     |    ^                            |
   |              PCF <--+    +-- NWDAF <-- usage reports  |
   |               |                 ^       every 30 s    |
   |               v                 |                     |
   |    AMF       SMF ------------- UPF                    |
   |     |         ^                 |                     |
   +-----|---------|-----------------|---------------------+
         |         |                 |
       gNB ---- ue1, ue2 (UERANSIM)  +--> data network (iperf3 server)
```

* The **UPF** measures how much data each UE sends and receives and reports
  it every 30 s.
* The **NWDAF** turns these reports into analytics (throughput per UE,
  QoS sustainability, ...).
* The **NEF** checks your AF's token and passes requests to the PCF (QoS) or
  the NWDAF (analytics).
* The **PCF** turns a QoS request into a rule. The SMF and UPF then apply it,
  for example by limiting a UE to 15 Mbit/s.

### Start everything

All commands are run from the `manifests` folder.

**1. Set the NEF secret** (used to sign AF tokens):

```bash
cd manifests
sed -i "s/REPLACE_WITH_SECRET/$(openssl rand -hex 32)/" conf/nef_config.yaml
```

**2. Start the stack, in this order:**

```bash
docker compose -f docker-compose-core.yaml up -d      # 5G core
sleep 30
docker compose -f docker-compose-nwdaf.yaml up -d     # NWDAF (after the core)
docker compose -f docker-compose-nef.yaml up -d       # NEF
sleep 20
docker compose -f docker-compose-ueransim.yaml up -d  # gNB + 2 UEs
```

**3. Check it works:**

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"   # all "Up" / "healthy"
docker exec ueransim-ue1 ip -4 addr show uesimtun0   # UE 1 has an IP
docker exec ueransim-ue2 ip -4 addr show uesimtun0   # UE 2 has an IP
docker exec ueransim-ue2 ping -c 3 -I uesimtun0 192.168.70.135
```

**4. Start traffic** so the network has something to measure:

```bash
./scripts/traffic.sh start 3600     # downlink iperf3 to both UEs, 1 hour
./scripts/traffic.sh stop
```

**Stop everything:**

```bash
docker compose -f docker-compose-ueransim.yaml down
docker compose -f docker-compose-nef.yaml down
docker compose -f docker-compose-nwdaf.yaml down
docker compose -f docker-compose-core.yaml down -v
```

> Always start the NWDAF **after** the core, and restart the NWDAF and NEF
> together. Both keep their subscriptions in memory only.

## Helpers & Resources

### RAN

The RAN is simulated with UERANSIM: one gNB and two UEs.

| Name | SUPI (UE ID) | IP | iperf3 port used by `traffic.sh` |
|---|---|---|---|
| `ueransim-ue1` | `imsi-208950000000035` | 12.1.1.10 (usually) | 5000 |
| `ueransim-ue2` | `imsi-208950000000034` | 12.1.1.9 (usually) | 5201 |

The IPs are given by the SMF. Check them with the `ip addr` command above.

Useful commands:

```bash
docker logs ueransim-ue2 | tail                    # attach and PDU session logs
docker exec ueransim-ue2 ip -4 addr show uesimtun0 # UE IP
# Your own traffic (example: 30 s of downlink to ue2 on port 5201)
docker exec -d ueransim-ue2 iperf3 -s -B 12.1.1.9 -p 5201
docker exec oai-ext-dn iperf3 -c 12.1.1.9 -p 5201 -t 30
```

### 5G Core

| Function | IP | What it does for you |
|---|---|---|
| NEF | 192.168.70.145:8080 | **The only API your AF uses** |
| PCF | 192.168.70.139 | Turns QoS requests into rules |
| SMF / UPF | .133 / .134 | Apply the rules, send usage reports |
| NWDAF events | 192.168.70.152:8080 | Analytics (reached through the NEF) |
| `oai-af` | 192.168.70.144 | A small container with `curl`, for trying things by hand |

All NEF APIs use **HTTP/2 without TLS** (`curl --http2-prior-knowledge`).
Notifications from the NEF to your AF can be HTTP/1.1 or HTTP/2.

#### Getting a token

Every NEF call needs a token. It says *who* your AF is and *which* NEF API it
may use:

```bash
./scripts/mint_jwt.py <your-af-name> <scope>
```

Run it without arguments to see the scopes. Your AF name must also be the
AF id in the NEF URLs.

To run `curl` from inside the core network, use the helper container:

```bash
docker exec oai-af curl -s --http2-prior-knowledge http://192.168.70.145:8080/...
```

#### The two NEF APIs you need

| What | NEF API | Where to read |
|---|---|---|
| Get analytics from the NWDAF | `/3gpp-analyticsexposure/v1/{afId}/subscriptions` | 3GPP TS 29.522, and the OpenAPI file `TS29522_AnalyticsExposure.yaml` |
| Change a UE's QoS | `/3gpp-as-session-with-qos/v1/{scsAsId}/subscriptions` | 3GPP TS 29.122, and the OpenAPI file `TS29122_AsSessionWithQoS.yaml` |

The OpenAPI files are in the
[`3gpp_specs/` folder of the NEF repository](https://github.com/openairinterface/oai-cn5g-nef/tree/pre_develop/3gpp_specs).
Working out the right requests is part of the challenge.

#### Values used in this setup

* DNN: `default`
* S-NSSAI: SST `222`, SD `00007b`
* Analytics this NWDAF can give: `QOS_SUSTAINABILITY`, `UE_COMM`,
  `NETWORK_PERFORMANCE`, `UE_MOBILITY`
* QoS profiles you can ask for (`qosReference`):

| `qosReference` | 5QI | Max rate down / up | Guaranteed rate |
|---|---|---|---|
| `OAI_QOS_GBR_VIDEO_1` | 2 | 15 / 15 Mbit/s | 10 Mbit/s |
| `OAI_QOS_GBR_LOWLAT_1` | 130 (low latency) | 20 / 20 Mbit/s | 15 Mbit/s |
| `OAI_QOS_NON_GBR_DEFAULT` | 9 | 50 / 25 Mbit/s | none |

The profiles are defined in
[`manifests/policies/qos_references/oai_qos_references.yaml`](manifests/policies/qos_references/oai_qos_references.yaml).
You can add your own; restart the PCF after editing.

#### Things specific to this setup

These are not in the specs, so they are written here:

* **Notification URLs** must use a host name, not an IP address. The NEF
  refuses private IP addresses such as 192.168.x.x.
  * AF on the Docker host: `http://af-host:<port>/...`
  * AF in a container on the `demo-oai-public-net` network:
    `http://<container-name>:<port>/...`
* **Naming a UE in analytics:** put its SUPI (`imsi-...`) where the spec
  expects a GPSI. A real NEF would translate a GPSI (such as an MSISDN).
* **Timing:** usage reports arrive every **30 s**, so a change in throughput
  takes 30–60 s to show up in the analytics.
* **A QoS session only affects the traffic that matches its flow description.**
* **Threshold alerts** do not say if the throughput went down or up.
* **Restarts:** the NEF and NWDAF keep subscriptions in memory only. If you
  restart one, restart both and subscribe again.
* `ABNORMAL_BEHAVIOR` analytics are not useful here (the score is always 100).

### Tools & Frameworks

* Any small web server can receive notifications (Flask, FastAPI,
  `http.server`, ...).
* **Watching what happens:**
  ```bash
  docker logs -f oai-nef                  # requests from your AF, notifications to it
  docker logs -f oai-nwdaf-nbi-events     # what the NWDAF evaluates and sends
  docker logs -f oai-pcf                  # the QoS rules that get created
  ```
* **ISAC:** bring in your sensing input (real or simulated) through any
  interface you like (REST, MQTT, file, ...), and use it in your AF's decision.

## References (optional)

* Documentation:
  * [OAI 5G Core federation repo and tutorials](https://github.com/openairinterface/oai-cn5g-fed)
  * [NEF documentation](https://github.com/openairinterface/oai-cn5g-nef/tree/pre_develop/docs)
* Specifications:
  * 3GPP TS 23.288: NWDAF and analytics architecture
  * 3GPP TS 29.522: NEF APIs for analytics (`3gpp-analyticsexposure`)
  * 3GPP TS 29.122: NEF API for QoS (`3gpp-as-session-with-qos`)
  * 3GPP TS 29.520: NWDAF APIs
  * 3GPP TS 29.514: PCF policy authorization
* Example implementations: none, that is your part
* Related repositories:
  * [oai-cn5g-nef](https://github.com/openairinterface/oai-cn5g-nef)
  * [oai-cn5g-nwdaf, branch feat/upf-ebpf](https://github.com/openairinterface/oai-cn5g-nwdaf)
  * [oai-cn5g-pcf, branch af-fix](https://github.com/openairinterface/oai-cn5g-pcf)

## Tasks

* [ ] Start the setup and check both UEs have an IP and traffic.
* [ ] Change a UE's QoS through the NEF, and see its throughput change.
* [ ] Get a notification from the NWDAF, through the NEF.
* [ ] Write your AF: subscribe, receive notifications, and change QoS on its own.
* [ ] Make your AF go back to normal when the problem is gone.
* [ ] Add an ISAC input (real or simulated) that changes your AF's decision.
* [ ] Handle both UEs, or use `UE_COMM` / `NETWORK_PERFORMANCE`
      analytics in your decision.

## Expected Result

A running AF that, without anyone touching it:

1. gets an alert from the NWDAF (through the NEF) when a UE's quality drops;
2. changes that UE's QoS through the NEF;
3. goes back to normal when the quality is fine again.

Participants should provide:

* a short demo: cause a quality drop (for example with competing traffic), and
  show the AF reacting;
* logs or a graph of the UE's throughput before, during and after the AF
  reacts;
* a short explanation of the AF's decision rule, and how ISAC input changes it.
* if you have used AI then please explain the models you have used and where it was used. 

## Validation / Evaluation

The organizers will:

* start the setup from `manifests/` and run your AF;
* change the traffic on the UEs and check that your AF reacts correctly
  (right UE, right QoS, back to normal afterwards);
* check that your AF uses **only the NEF** APIs.

Points for:

* **Clarity:** clean code and a short, clear README
* **It works:** a full loop in the demo
* **Good decisions:** reacts quickly, doesn't flip back and forth, and cleans up
  (deletes its subscriptions and QoS sessions)

## Deliverables

* Source code / patches: your AF, plus any changes to the setup
* Documentation: a short README with how to run your AF and its decision rule
* Configuration files: anything you changed in `manifests/` (QoS profiles, ...)
* Test results: logs or a throughput graph showing the loop
* Demo / presentation (Slides or Markdown with diagrams): 5 minutes
* Send the code git repository link with slides/markdown on oaicicdteam@openairinterface.org

## Support

Ask Rupanjali or Sagar Arora (sagar.arora@openairinterface.org)
