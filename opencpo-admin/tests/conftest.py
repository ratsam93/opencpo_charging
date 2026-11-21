import os
import sys

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("OCPP_CORE_API", "http://127.0.0.1:1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
