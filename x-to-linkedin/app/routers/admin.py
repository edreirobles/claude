"""
Endpoints de administración: git pull y reinicio del servidor.
"""
import subprocess
import sys
import os
import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


@router.post("/git-pull")
async def git_pull():
    """Ejecuta git pull en el directorio del proyecto."""
    try:
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            timeout=30,
        )
        output = result.stdout + result.stderr
        success = result.returncode == 0
        logger.info(f"git pull result: {output}")
        return {"success": success, "output": output.strip()}
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=500, content={"success": False, "output": "Timeout al ejecutar git pull"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "output": str(e)})


@router.post("/restart")
async def restart_server():
    """Reinicia el proceso uvicorn reemplazando el proceso actual."""
    try:
        logger.info("Reiniciando servidor por petición de admin...")
        # Ejecutar en background para que la respuesta llegue antes del restart
        subprocess.Popen(
            ["bash", "-c", "sleep 1 && kill -HUP " + str(os.getpid())],
        )
        return {"success": True, "output": "Reiniciando en 1 segundo..."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "output": str(e)})


@router.post("/pull-and-restart")
async def pull_and_restart():
    """Hace git pull y luego reinicia el servidor."""
    # Primero el pull
    try:
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            timeout=30,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            return JSONResponse(status_code=500, content={"success": False, "output": output.strip()})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "output": str(e)})

    # Luego el restart
    try:
        subprocess.Popen(
            ["bash", "-c", "sleep 1 && kill -HUP " + str(os.getpid())],
        )
        return {"success": True, "output": f"Pull OK:\n{output.strip()}\n\nReiniciando en 1 segundo..."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "output": str(e)})
