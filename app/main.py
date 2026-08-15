import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field


app = FastAPI(title="Simple Code Runner")


# --------------------------------------------------
# Configuration
# --------------------------------------------------

MAX_CODE_SIZE = 50_000       # 50 KB
MAX_INPUT_SIZE = 10_000      # 10 KB
TIMEOUT_SECONDS = 5
MEMORY_LIMIT_MB = 128


# --------------------------------------------------
# Request model
# --------------------------------------------------

class RunRequest(BaseModel):
    language: str
    code: str = Field(max_length=MAX_CODE_SIZE)
    stdin: str = Field(default="", max_length=MAX_INPUT_SIZE)


# --------------------------------------------------
# Resource limits
# --------------------------------------------------

def set_limits():
    """
    Applied inside the child process.
    """

    try:
        import resource

        # CPU time
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (TIMEOUT_SECONDS, TIMEOUT_SECONDS)
        )

        # Maximum address space / memory
        memory = MEMORY_LIMIT_MB * 1024 * 1024

        resource.setrlimit(
            resource.RLIMIT_AS,
            (memory, memory)
        )

        # Maximum number of processes
        resource.setrlimit(
            resource.RLIMIT_NPROC,
            (20, 20)
        )

        # Maximum number of open files
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (64, 64)
        )

        # Maximum output file size
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (2 * 1024 * 1024, 2 * 1024 * 1024)
        )

    except Exception:
        pass


# --------------------------------------------------
# Environment
# --------------------------------------------------

def safe_environment():
    """
    Don't expose the Render environment variables
    to submitted programs.
    """

    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


# --------------------------------------------------
# Execute command
# --------------------------------------------------

def execute(
    command,
    cwd,
    stdin_data=""
):
    start = time.perf_counter()

    try:
        process = subprocess.run(
            command,
            input=stdin_data,
            text=True,
            capture_output=True,
            cwd=cwd,

            # NEVER use shell=True
            shell=False,

            timeout=TIMEOUT_SECONDS,

            env=safe_environment(),

            preexec_fn=set_limits,

        )

        elapsed = time.perf_counter() - start

        return {
            "success": process.returncode == 0,
            "return_code": process.returncode,
            "stdout": process.stdout[:2_000_000],
            "stderr": process.stderr[:2_000_000],
            "time": round(elapsed, 4),
        }

    except subprocess.TimeoutExpired as e:

        return {
            "success": False,
            "return_code": -1,
            "stdout": e.stdout or "",
            "stderr": "Execution timed out.",
            "time": TIMEOUT_SECONDS,
        }

    except Exception as e:

        return {
            "success": False,
            "return_code": -1,
            "stdout": "",
            "stderr": str(e),
            "time": round(time.perf_counter() - start, 4),
        }


# --------------------------------------------------
# Python
# --------------------------------------------------

def run_python(code, stdin_data, directory):

    source = Path(directory) / "main.py"

    source.write_text(
        code,
        encoding="utf-8"
    )

    return execute(
        [
            "python3",
            str(source)
        ],
        directory,
        stdin_data
    )


# --------------------------------------------------
# C
# --------------------------------------------------

def run_c(code, stdin_data, directory):

    source = Path(directory) / "main.c"
    executable = Path(directory) / "main"

    source.write_text(
        code,
        encoding="utf-8"
    )

    compile_result = execute(
        [
            "gcc",
            str(source),
            "-O2",
            "-o",
            str(executable)
        ],
        directory
    )

    if not compile_result["success"]:

        return {
            "success": False,
            "status": "Compilation Error",
            "stdout": "",
            "stderr": compile_result["stderr"],
            "compile_output": compile_result["stderr"],
            "time": compile_result["time"],
        }

    result = execute(
        [str(executable)],
        directory,
        stdin_data
    )

    result["compile_output"] = ""

    return result


# --------------------------------------------------
# C++
# --------------------------------------------------

def run_cpp(code, stdin_data, directory):

    source = Path(directory) / "main.cpp"
    executable = Path(directory) / "main"

    source.write_text(
        code,
        encoding="utf-8"
    )

    compile_result = execute(
        [
            "g++",
            str(source),
            "-O2",
            "-std=c++17",
            "-o",
            str(executable)
        ],
        directory
    )

    if not compile_result["success"]:

        return {
            "success": False,
            "status": "Compilation Error",
            "stdout": "",
            "stderr": compile_result["stderr"],
            "compile_output": compile_result["stderr"],
            "time": compile_result["time"],
        }

    result = execute(
        [str(executable)],
        directory,
        stdin_data
    )

    result["compile_output"] = ""

    return result


# --------------------------------------------------
# Java
# --------------------------------------------------

def run_java(code, stdin_data, directory):

    source = Path(directory) / "Main.java"

    source.write_text(
        code,
        encoding="utf-8"
    )

    compile_result = execute(
        [
            "javac",
            str(source)
        ],
        directory
    )

    if not compile_result["success"]:

        return {
            "success": False,
            "status": "Compilation Error",
            "stdout": "",
            "stderr": compile_result["stderr"],
            "compile_output": compile_result["stderr"],
            "time": compile_result["time"],
        }

    result = execute(
        [
            "java",
            "-Xmx128m",
            "-Xss1m",
            "-cp",
            directory,
            "Main"
        ],
        directory,
        stdin_data
    )

    result["compile_output"] = ""

    return result


# --------------------------------------------------
# Main endpoint
# --------------------------------------------------

@app.post("/run")
def run_code(request: RunRequest):

    language = request.language.lower().strip()

    allowed = {
        "python",
        "py",
        "c",
        "cpp",
        "c++",
        "java",
    }

    if language not in allowed:

        return {
            "success": False,
            "status": "Unsupported language",
        }

    # Temporary directory for THIS execution
    with tempfile.TemporaryDirectory(
        prefix="code_",
        dir="/tmp"
    ) as directory:

        if language in ["python", "py"]:

            result = run_python(
                request.code,
                request.stdin,
                directory
            )

        elif language == "c":

            result = run_c(
                request.code,
                request.stdin,
                directory
            )

        elif language in ["cpp", "c++"]:

            result = run_cpp(
                request.code,
                request.stdin,
                directory
            )

        elif language == "java":

            result = run_java(
                request.code,
                request.stdin,
                directory
            )

        else:

            return {
                "success": False,
                "status": "Unsupported language"
            }

    # Determine status
    if result.get("status"):
        status = result["status"]

    elif result["success"]:
        status = "Accepted"

    elif "timed out" in result["stderr"].lower():
        status = "Time Limit Exceeded"

    else:
        status = "Runtime Error"

    return {
        "success": result["success"],
        "status": status,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "compile_output": result.get("compile_output", ""),
        "return_code": result.get("return_code"),
        "time": result.get("time"),
    }


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/")
def home():

    return {
        "status": "online",
        "service": "Simple Code Runner",
        "languages": [
            "python",
            "c",
            "cpp",
            "java"
        ]
    }


@app.get("/health")
def health():

    return {
        "status": "healthy"
    }