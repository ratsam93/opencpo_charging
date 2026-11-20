#!/bin/bash
W="/tmp/claude-0/-home-user-opencpo-charging/2936cd10-93d7-581c-a553-2f427033b420/scratchpad/t20/T11"; PY=$W/venv/bin/python; cd $W
: > $W/mock_core.jsonl
cleanup(){ kill $MP $AP 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT
$PY -m uvicorn --app-dir $W mock_core:app --host 127.0.0.1 --port 18101 --log-level warning > $W/mock4.out 2>&1 &
MP=$!
(cd $W/charge-app && OCPP_CORE_API=http://127.0.0.1:18101 MANAGEMENT_API_KEY=mgmt-KEY-T11 JWT_SECRET=t11-secret-value APP_PORT=18100 $PY -m uvicorn main:app --host 127.0.0.1 --port 18100 > $W/app4.out 2>&1) &
AP=$!
C="curl -s --max-time 10"
curl -s --max-time 5 --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null http://127.0.0.1:18101/api/v1/features && echo mock-up
curl -s --max-time 5 --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null http://127.0.0.1:18100/ && echo app-up
echo "=== T1a plain client, X-Client-Cert-Serial: ABC123 -> Set-Cookie on /"
$C -D - -o /dev/null -H "X-Client-Cert-Serial: ABC123" http://127.0.0.1:18100/ | grep -i "^set-cookie" | sed 's/=[^;]*;/=<JWT>;/'
echo "=== T1a /account/profile with cert header only"
$C -o $W/t1p.html -w "HTTP %{http_code}\n" -H "X-Client-Cert-Serial: ABC123" http://127.0.0.1:18100/account/profile
grep -o "Victim Driver" $W/t1p.html | head -1
$C -D $W/h4.txt -o /dev/null -H "X-Client-Cert-Serial: ABC123" http://127.0.0.1:18100/
$PY - <<PYEOF
import re
h=open("$W/h4.txt").read()
m=re.search(r"^set-cookie: device_auth=([^;\r\n]+)", h, re.I|re.M)
open("$W/dc4.txt","w").write(m.group(1))
PYEOF
DC=$(cat $W/dc4.txt)
echo "=== T1b device_auth replayed with NO cert header: /account/settings"
echo -n "with cookie: "; $C -o $W/s1.html -w "HTTP %{http_code}\n" --cookie "device_auth=$DC" http://127.0.0.1:18100/account/settings
echo -n "no cookie:   "; $C -o $W/s0.html -w "HTTP %{http_code}\n" http://127.0.0.1:18100/account/settings
grep -c "Victim Driver" $W/s1.html
echo "=== T1c anonymous probe to core-backed poll"
$C -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:18100/api/sessions/ANON-PROBE/poll
echo "=== T2 no cookie, other session VICTIM-SESS"
for u in "GET /api/sessions/VICTIM-SESS/poll" "GET /api/sessions/VICTIM-SESS/receipt" "GET /api/sessions/VICTIM-SESS/pdf" "POST /api/sessions/VICTIM-SESS/stop" "POST /api/sessions/VICTIM-SESS/cancel" "GET /session/VICTIM-SESS" "GET /receipt/VICTIM-SESS"; do
  set -- $u
  $C -X $1 -o $W/t2b.txt -w "%{http_code} $1 $2 " http://127.0.0.1:18100$2; head -c 110 $W/t2b.txt | tr '\n' ' '; echo
done
echo "=== T3 core 500 body SECRET-TRACE"
$C -w "\nHTTP %{http_code}\n" http://127.0.0.1:18100/api/sessions/BOOM-SESSION/poll
$C -w "\nHTTP %{http_code}\n" http://127.0.0.1:18100/api/sessions/BOOM-SESSION/receipt
$C -X POST -w "\nHTTP %{http_code}\n" http://127.0.0.1:18100/api/sessions/BOOM-SESSION/stop
echo "=== T4 login cookie flags"
$C -D - -o /dev/null -H "Content-Type: application/json" -d '{"email":"victim@example.test","password":"x"}' http://127.0.0.1:18100/api/account/login | grep -i "^set-cookie"
echo "=== T5 security headers"
for path in / /account/login /account/settings /api/sessions/X/poll; do echo "-- $path"; $C -D - -o /dev/null http://127.0.0.1:18100$path | grep -i "^HTTP\|content-security\|strict-transport\|x-frame\|x-content-type\|referrer-policy\|permissions-policy" | tr -d '\r'; done
echo "=== core-side headers (first 14 records)"
$PY -c "
import json
rows=[json.loads(l) for l in open('$W/mock_core.jsonl')]
for r in rows[:14]:
    h={k:v for k,v in r['headers'].items() if k in ('x-api-key','authorization','x-client-cert-serial','cookie')}
    print(r['method'], r['path'], r['query'], h)
print('total core requests:', len(rows))
"
