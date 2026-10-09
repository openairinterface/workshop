#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Make the token your AF sends to the NEF ("Authorization: Bearer <token>").

    ./scripts/mint_jwt.py <af_id> <scope>

  af_id  your AF name; must be the same as the {afId}/{scsAsId} in the NEF URL
  scope  the NEF API the token is for:
           nnef-qosmonitoring      AS session with QoS (change QoS)
           nnef-analyticsexposure  analytics from the NWDAF
           nnef-eventexposure      monitoring events

The secret is read from conf/nef_config.yaml (nef.security.jwt_secret).
"""
import base64, hashlib, hmac, json, os, re, sys, time

def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

if len(sys.argv) != 3:
    sys.exit(__doc__)
af_id, scope = sys.argv[1], sys.argv[2]
conf = os.path.join(os.path.dirname(__file__), "..", "conf", "nef_config.yaml")
m = re.search(r'jwt_secret:\s*"([^"]+)"', open(conf).read())
if not m or m.group(1) == "REPLACE_WITH_SECRET":
    sys.exit("Set nef.security.jwt_secret in conf/nef_config.yaml first (see README).")
header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
claims = b64(json.dumps({"sub": af_id, "scope": scope, "iat": int(time.time())}).encode())
sig = hmac.new(m.group(1).encode(), f"{header}.{claims}".encode(), hashlib.sha256).digest()
print(f"{header}.{claims}.{b64(sig)}")
