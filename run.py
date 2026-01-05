import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

backend_process = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
    stdout=sys.stdout,
    stderr=sys.stderr
)

os.chdir("frontend")
frontend_process = subprocess.Popen(
    ["npm", "run", "dev"],
    stdout=sys.stdout,
    stderr=sys.stderr
)

try:
    backend_process.wait()
    frontend_process.wait()
except KeyboardInterrupt:
    backend_process.terminate()
    frontend_process.terminate()
