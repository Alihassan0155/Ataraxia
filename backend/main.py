
from fastapi import FastAPI

app = FastAPI(
    title="Ataraxia API",
    description="Backend API for the Ataraxia recommendation system",
    version="0.1.0"
)


@app.get("/")
def root():
    return {"message": "Welcome to the Ataraxia API"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}