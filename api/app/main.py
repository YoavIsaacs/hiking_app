from fastapi import FastAPI

app = FastAPI(title="Hike Prep API")


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}
