import os
import resource
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="Simple Code Runner")

# ============================================================
# CORS
# ============================================================

# Define the CORS middleware
origins = [  # Allow frontend running on localhost:5173
    "*"
]

# Add CORSMiddleware to the FastAPI app
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Specify the allowed origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

# ============================================================
# CONFIGURATION
# ============================================================

MAX_CODE_SIZE = 50_000
MAX_INPUT_SIZE = 10_000
MAX_OUTPUT_SIZE = 2_000_000

RUN_TIMEOUT = 5
COMPILE_TIMEOUT = 15

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_OPEN_FILES = 128


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

def set_limits(timeout=5):
    """
    Apply only lightweight limits.

    IMPORTANT:
    We intentionally DO NOT use:

        RLIMIT_NPROC
        RLIMIT_AS

    because GCC/G++/Java need to create child processes
    and allocate memory while compiling.
    """

    try:

        # ----------------------------------------------------
        # CPU TIME
        # ----------------------------------------------------

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (timeout, timeout)
        )

    except Exception:
        pass

    try:

        # ----------------------------------------------------
        # MAX OPEN FILES
        # ----------------------------------------------------

        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (
                MAX_OPEN_FILES,
                MAX_OPEN_FILES
            )
        )

    except Exception:
        pass

    try:

        # ----------------------------------------------------
        # MAX FILE SIZE
        # ----------------------------------------------------

        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (
                MAX_FILE_SIZE,
                MAX_FILE_SIZE
            )
        )

    except Exception:
        pass


# ============================================================
# SAFE ENVIRONMENT
# ============================================================

def safe_environment():

    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8"
    }


# ============================================================
# EXECUTE COMMAND
# ============================================================

def execute(
    command,
    cwd,
    stdin_data="",
    timeout=RUN_TIMEOUT,
    apply_limits=True
):

    start = time.perf_counter()

    try:

        if apply_limits:

            preexec = lambda: set_limits(
                timeout
            )

        else:

            preexec = None

        process = subprocess.run(

            command,

            input=stdin_data,

            text=True,

            capture_output=True,

            cwd=cwd,

            shell=False,

            timeout=timeout,

            env=safe_environment(),

            preexec_fn=preexec
        )

        elapsed = (
            time.perf_counter() - start
        )

        return {

            "success":
                process.returncode == 0,

            "return_code":
                process.returncode,

            "stdout":
                process.stdout[
                    :MAX_OUTPUT_SIZE
                ],

            "stderr":
                process.stderr[
                    :MAX_OUTPUT_SIZE
                ],

            "time":
                round(elapsed, 4)
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

            "stdout":
                stdout[
                    :MAX_OUTPUT_SIZE
                ],

            "stderr":
                "Execution timed out.",

            "time":
                timeout
        }

    except Exception as e:

        return {

            "success": False,

            "return_code": -1,

            "stdout": "",

            "stderr": str(e),

            "time":
                round(
                    time.perf_counter()
                    - start,
                    4
                )
        }


# ============================================================
# PYTHON
# ============================================================

def run_python(
    code,
    stdin_data,
    directory
):

    source = (
        Path(directory)
        / "main.py"
    )

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

        timeout=RUN_TIMEOUT,

        apply_limits=True
    )


# ============================================================
# C
# ============================================================

def run_c(
    code,
    stdin_data,
    directory
):

    source = (
        Path(directory)
        / "main.c"
    )

    executable = (
        Path(directory)
        / "main"
    )

    source.write_text(
        code,
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # COMPILE
    #
    # IMPORTANT:
    # No resource limits during compilation.
    # GCC needs to spawn cc1.
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

        apply_limits=False
    )

    if not compile_result["success"]:

        return {

            "success": False,

            "status":
                "Compilation Error",

            "stdout": "",

            "stderr":
                compile_result["stderr"],

            "compile_output":
                compile_result["stderr"],

            "time":
                compile_result["time"],

            "return_code":
                compile_result[
                    "return_code"
                ]
        }

    # --------------------------------------------------------
    # RUN
    # --------------------------------------------------------

    result = execute(

        [
            str(executable)
        ],

        directory,

        stdin_data,

        timeout=RUN_TIMEOUT,

        apply_limits=True
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

    source = (
        Path(directory)
        / "main.cpp"
    )

    executable = (
        Path(directory)
        / "main"
    )

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

        apply_limits=False
    )

    if not compile_result["success"]:

        return {

            "success": False,

            "status":
                "Compilation Error",

            "stdout": "",

            "stderr":
                compile_result["stderr"],

            "compile_output":
                compile_result["stderr"],

            "time":
                compile_result["time"],

            "return_code":
                compile_result[
                    "return_code"
                ]
        }

    # --------------------------------------------------------
    # RUN
    # --------------------------------------------------------

    result = execute(

        [
            str(executable)
        ],

        directory,

        stdin_data,

        timeout=RUN_TIMEOUT,

        apply_limits=True
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

    source = (
        Path(directory)
        / "Main.java"
    )

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

        apply_limits=False
    )

    if not compile_result["success"]:

        return {

            "success": False,

            "status":
                "Compilation Error",

            "stdout": "",

            "stderr":
                compile_result["stderr"],

            "compile_output":
                compile_result["stderr"],

            "time":
                compile_result["time"],

            "return_code":
                compile_result[
                    "return_code"
                ]
        }

    # --------------------------------------------------------
    # RUN
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

        timeout=RUN_TIMEOUT,

        apply_limits=True
    )

    result["compile_output"] = ""

    return result


# ============================================================
# MAIN ENDPOINT
# ============================================================

@app.post("/run")
def run_code(
    request: RunRequest
):

    language = (
        request.language
        .lower()
        .strip()
    )

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

            "status":
                "Unsupported language",

            "stdout": "",

            "stderr":
                "Supported languages: "
                "Python, C, C++, Java",

            "compile_output": ""
        }

    try:

        with tempfile.TemporaryDirectory(
            prefix="code_",
            dir="/tmp"
        ) as directory:

            # ------------------------------------------------
            # PYTHON
            # ------------------------------------------------

            if language in [
                "python",
                "py"
            ]:

                result = run_python(

                    request.code,

                    request.stdin,

                    directory
                )

            # ------------------------------------------------
            # C
            # ------------------------------------------------

            elif language == "c":

                result = run_c(

                    request.code,

                    request.stdin,

                    directory
                )

            # ------------------------------------------------
            # C++
            # ------------------------------------------------

            elif language in [
                "cpp",
                "c++"
            ]:

                result = run_cpp(

                    request.code,

                    request.stdin,

                    directory
                )

            # ------------------------------------------------
            # JAVA
            # ------------------------------------------------

            elif language == "java":

                result = run_java(

                    request.code,

                    request.stdin,

                    directory
                )

            else:

                return {

                    "success": False,

                    "status":
                        "Unsupported language"
                }

    except Exception as e:

        return {

            "success": False,

            "status":
                "Runner Error",

            "stdout": "",

            "stderr":
                str(e),

            "compile_output": ""
        }

    # ========================================================
    # STATUS
    # ========================================================

    if result.get("status"):

        status = result["status"]

    elif result["success"]:

        status = "Accepted"

    elif (
        "timed out"
        in result.get(
            "stderr",
            ""
        ).lower()
    ):

        status = (
            "Time Limit Exceeded"
        )

    else:

        status = "Runtime Error"

    # ========================================================
    # RESPONSE
    # ========================================================

    return {

        "success":
            result["success"],

        "status":
            status,

        "stdout":
            result.get(
                "stdout",
                ""
            ),

        "stderr":
            result.get(
                "stderr",
                ""
            ),

        "compile_output":
            result.get(
                "compile_output",
                ""
            ),

        "return_code":
            result.get(
                "return_code"
            ),

        "time":
            result.get(
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

        "service":
            "Simple Code Runner",

        "languages": [

            "python",

            "c",

            "cpp",

            "java"
        ]
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "healthy"
        }
