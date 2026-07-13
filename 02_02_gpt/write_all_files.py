import os, sys

base = "/home/nv_test/777/flashdb2rust/02_02/flashDB_rust/src"

def w(path, content):
    full_path = os.path.join(base, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(content)
    sys.exit(0)
