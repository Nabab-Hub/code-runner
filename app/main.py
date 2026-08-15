import resource
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field


app = FastAPI(title="Simple Code Runner")


# ============================================================
# CONFIGURATION
# ============================================================

MAX_CODE_SIZE = 50_000          # 50 KB
MAX_INPUT_SIZE = 10_000         # 10 KB
MAX_OUTPUT_SIZE = 2_000_000     # 2 MB

DEFAULT_TIMEOUT = 5
COMPILE_TIMEOUT = 15

# Render Free has limited RAM.
# Keep some RAM available for FastAPI itself.
DEFAULT_MEMORY_MB = 384

# Allow compiler processes such as gcc -> cc1
MAX_PROCESSES = 100

MAX_OPEN_FILES = 128

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# ============================================================
# REQUEST MODEL
# ============================================================

class RunRequest(BaseModel):
    language: str

    code: str = Field(
        ...,
        max_length=MAX_CODE_SIZE
    )

    stdin: str = Field(
        default="",
        max_length=MAX_INPUT_SIZE
    )


# ============================================================
# RESOURCE LIMITS
# ============================================================

def set_limits(
    timeout: int = DEFAULT_TIMEOUT,
    memory_mb: int = DEFAULT_MEMORY_MB,
    processes: int = MAX_PROCESSES
):
    """
    Apply resource limits to the child process.

    These limits are useful for a small project but should NOT
    be considered a complete security sandbox.
    """

    try:

        # ----------------------------------------------------
        # CPU TIME
        # ----------------------------------------------------

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (timeout, timeout)
        )

        # ----------------------------------------------------
        # MEMORY
        # ----------------------------------------------------

        memory = memory_mb * 1024 * 1024

        resource.setrlimit(
            resource.RLIMIT_AS,
            (memory, memory)
        )

        # ----------------------------------------------------
        # NUMBER OF PROCESSES / THREADS
        # ----------------------------------------------------

        resource.setrlimit(
            resource.RLIMIT_NPROC,
            (processes, processes)
        )

        # ----------------------------------------------------
        # OPEN FILES
        # ----------------------------------------------------

        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (MAX_OPEN_FILES, MAX_OPEN_FILES)
        )

        # ----------------------------------------------------
        # MAXIMUM FILE SIZE
        # ----------------------------------------------------

        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (MAX_FILE_SIZE, MAX_FILE_SIZE)
        )

    except Exception:
        # Some limits may not be available in every environment.
        pass


# ============================================================
# SAFE ENVIRONMENT
# ============================================================

def safe_environment():
    """
    Do not expose Render environment variables or API keys
    to submitted programs.
    """

    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


# ============================================================
# EXECUTION FUNCTION
# ============================================================

def execute(
    command,
    cwd,
    stdin_data="",
    timeout=DEFAULT_TIMEOUT,
    memory_mb=DEFAULT_MEMORY_MB,
    processes=MAX_PROCESSES
):

    start = time.perf_counter()

    try:

        process = subprocess.run(

            command,

            input=stdin_data,

            text=True,

            capture_output=True,

            cwd=cwd,

            # VERY IMPORTANT
            # Never use shell=True for user code.
            shell=False,

            timeout=timeout,

            env=safe_environment(),

            preexec_fn=lambda: set_limits(
                timeout=timeout,
                memory_mb=memory_mb,
                processes=processes
            ),
        )

        elapsed = time.perf_counter() - start

        return {
            "success": process.returncode == 0,

            "return_code": process.returncode,

            "stdout": process.stdout[:MAX_OUTPUT_SIZE],

            "stderr": process.stderr[:MAX_OUTPUT_SIZE],

            "time": round(elapsed, 4),
        }

    except subprocess.TimeoutExpired as e:

        stdout = e.stdout or ""
        stderr = e.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode(
                "utf-8",
                errors="replace"
            )

        if isinstance(stderr, bytes):
            stderr = stderr.decode(
                "utf-8",
                errors="replace"
            )

        return {
            "success": False,

            "return_code": -1,

            "stdout": stdout[:MAX_OUTPUT_SIZE],

            "stderr": "Execution timed out.",

            "time": timeout,
        }

    except MemoryError:

        return {
            "success": False,

            "return_code": -1,

            "stdout": "",

            "stderr": "Memory limit exceeded.",

            "time": round(
                time.perf_counter() - start,
                4
            ),
        }

    except Exception as e:

        return {
            "success": False,

            "return_code": -1,

            "stdout": "",

            "stderr": str(e),

            "time": round(
                time.perf_counter() - start,
                4
            ),
        }


# ============================================================
# PYTHON
# ============================================================

def run_python(
    code,
    stdin_data,
    directory
):

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

        stdin_data,

        timeout=DEFAULT_TIMEOUT,

        memory_mb=DEFAULT_MEMORY_MB,

        processes=MAX_PROCESSES
    )


# ============================================================
# C
# ============================================================

def run_c(
    code,
    stdin_data,
    directory
):

    source = Path(directory) / "main.c"

    executable = Path(directory) / "main"

    source.write_text(
        code,
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # COMPILE
    # --------------------------------------------------------

    compile_result = execute(

        [
            "gcc",
            str(source),
            "-O2",
            "-o",
            str(executable)
        ],

        directory,

        timeout=COMPILE_TIMEOUT,

        memory_mb=DEFAULT_MEMORY_MB,

        processes=MAX_PROCESSES
    )

    if not compile_result["success"]:

        return {
            "success": False,

            "status": "Compilation Error",

            "stdout": "",

            "stderr": compile_result["stderr"],

            "compile_output": compile_result["stderr"],

            "time": compile_result["time"],

            "return_code": compile_result["return_code"]
        }

    # --------------------------------------------------------
    # RUN
    # --------------------------------------------------------

    result = execute(

        [str(executable)],

        directory,

        stdin_data,

        timeout=DEFAULT_TIMEOUT,

        memory_mb=DEFAULT_MEMORY_MB,

        processes=MAX_PROCESSES
    )

    result["compile_output"] = ""

    return result


# ============================================================
# C++
# ============================================================

def run_cpp(
    code,
    stdin_data,
    directory
):

    source = Path(directory) / "main.cpp"

    executable = Path(directory) / "main"

    source.write_text(
        code,
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # COMPILE
    # --------------------------------------------------------

    compile_result = execute(

        [
            "g++",
            str(source),
            "-O2",
            "-std=c++17",
            "-o",
            str(executable)
        ],

        directory,

        timeout=COMPILE_TIMEOUT,

        memory_mb=DEFAULT_MEMORY_MB,

        processes=MAX_PROCESSES
    )

    if not compile_result["success"]:

        return {
            "success": False,

            "status": "Compilation Error",

            "stdout": "",

            "stderr": compile_result["stderr"],

            "compile_output": compile_result["stderr"],

            "time": compile_result["time"],

            "return_code": compile_result["return_code"]
        }

    # --------------------------------------------------------
    # RUN
    # --------------------------------------------------------

    result = execute(

        [str(executable)],

        directory,

        stdin_data,

        timeout=DEFAULT_TIMEOUT,

        memory_mb=DEFAULT_MEMORY_MB,

        processes=MAX_PROCESSES
    )

    result["compile_output"] = ""

    return result


# ============================================================
# JAVA
# ============================================================

def run_java(
    code,
    stdin_data,
    directory
):

    source = Path(directory) / "Main.java"

    source.write_text(
        code,
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # COMPILE
    # --------------------------------------------------------

    compile_result = execute(

        [
            "javac",
            str(source)
        ],

        directory,

        timeout=COMPILE_TIMEOUT,

        memory_mb=DEFAULT_MEMORY_MB,

        processes=MAX_PROCESSES
    )

    if not compile_result["success"]:

        return {
            "success": False,

            "status": "Compilation Error",

            "stdout": "",

            "stderr": compile_result["stderr"],

            "compile_output": compile_result["stderr"],

            "time": compile_result["time"],

            "return_code": compile_result["return_code"]
        }

    # --------------------------------------------------------
    # RUN JAVA
    # --------------------------------------------------------

    result = execute(

        [
            "java",

            "-Xmx256m",

            "-Xss1m",

            "-cp",

            directory,

            "Main"
        ],

        directory,

        stdin_data,

        timeout=DEFAULT_TIMEOUT,

        memory_mb=DEFAULT_MEMORY_MB,

        processes=MAX_PROCESSES
    )

    result["compile_output"] = ""

    return result


# ============================================================
# MAIN RUN ENDPOINT
# ============================================================

@app.post("/run")
def run_code(request: RunRequest):

    language = request.language.lower().strip()

    # --------------------------------------------------------
    # ALLOWED LANGUAGES
    # --------------------------------------------------------

    allowed_languages = {
        "python",
        "py",
        "c",
        "cpp",
        "c++",
        "java"
    }

    if language not in allowed_languages:

        return {
            "success": False,

            "status": "Unsupported language",

            "stdout": "",

            "stderr": (
                "Supported languages: "
                "Python, C, C++, Java"
            )
        }

    # --------------------------------------------------------
    # CREATE TEMPORARY DIRECTORY
    # --------------------------------------------------------

    try:

        with tempfile.TemporaryDirectory(
            prefix="code_",
            dir="/tmp"
        ) as directory:

            # -----------------------------------------------
            # PYTHON
            # -----------------------------------------------

            if language in ["python", "py"]:

                result = run_python(

                    request.code,

                    request.stdin,

                    directory
                )

            # -----------------------------------------------
            # C
            # -----------------------------------------------

            elif language == "c":

                result = run_c(

                    request.code,

                    request.stdin,

                    directory
                )

            # -----------------------------------------------
            # C++
            # -----------------------------------------------

            elif language in ["cpp", "c++"]:

                result = run_cpp(

                    request.code,

                    request.stdin,

                    directory
                )

            # -----------------------------------------------
            # JAVA
            # -----------------------------------------------

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

    except Exception as e:

        return {
            "success": False,

            "status": "Runner Error",

            "stdout": "",

            "stderr": str(e)
        }

    # ========================================================
    # DETERMINE FINAL STATUS
    # ========================================================

    if result.get("status"):

        status = result["status"]

    elif result["success"]:

        status = "Accepted"

    elif (
        "timed out"
        in result.get("stderr", "").lower()
    ):

        status = "Time Limit Exceeded"

    else:

        status = "Runtime Error"

    # ========================================================
    # RESPONSE
    # ========================================================

    return {

        "success": result["success"],

        "status": status,

        "stdout": result.get(
            "stdout",
            ""
        ),

        "stderr": result.get(
            "stderr",
            ""
        ),

        "compile_output": result.get(
            "compile_output",
            ""
        ),

        "return_code": result.get(
            "return_code"
        ),

        "time": result.get(
            "time"
        )
    }


# ============================================================
# HOME
# ============================================================

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


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "healthy"
    }

@app.get("/debug")
def debug():

    import os
    import subprocess

    result = {}

    try:
        result["gcc_version"] = subprocess.run(
            ["gcc", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        ).stdout.splitlines()[0]
    except Exception as e:
        result["gcc_error"] = str(e)

    try:
        result["gpp_version"] = subprocess.run(
            ["g++", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        ).stdout.splitlines()[0]
    except Exception as e:
        result["gpp_error"] = str(e)

    try:
        result["java_version"] = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        ).stderr
    except Exception as e:
        result["java_error"] = str(e)

    try:
        result["javac_version"] = subprocess.run(
            ["javac", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        ).stderr
    except Exception as e:
        result["javac_error"] = str(e)

    result["cpu_count"] = os.cpu_count()

    return result
