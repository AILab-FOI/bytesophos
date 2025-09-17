# run.py

"""
Entry point to run the FastAPI app with Uvicorn.

This script starts the bytesophos API server when executed directly.

Usage:
    python run.py 

It loads the `app` instance from `app.main` and serves it on
`http://0.0.0.0:3001`.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=3001)
