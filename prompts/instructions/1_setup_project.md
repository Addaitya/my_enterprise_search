# Project Setup
Note before anything:
    - Run and execute code to check for working
    - Don't move forward before solving issue in code.
    - Where you can't check things, give human instruction to verify and give feedback.
# Tech stack
- Backend: Fastapi
    - ORM: sqlalchemy
    - db schema version control: alembic
    - package manager: uv
- Database: Postgres db 
- Search layer: openai
- Auth layer: Keycloak
- Object storage: Minio
- Frontend: 
    - library: React
    - css: tailwind
    - state management: Zustand
    - package manager: bun


## Step 1: Setup File system
Create two folders backend and frontend
-Backend
    - Create an ideal project setup that is suitable for backend.
    - For config management we will use 
        - pydantic-settings for non-sensitive values and sensitive value are imported from .env
        - .env: store sensitive values
        - Some values are generate at run time will be stored in pydantic setting object,
            - but during development will not generate those config values again and again so store it in json file.
    - Create `init_services` directory where we can initialise the the docker services by api calls.
- Frontend
    - Create an ideal project setup that is suitable for react. 
        - Setup tailwind
        - State management 
        - Components
            - ui
            - layout
        - Enternal api calls
        - Hooks 
        - Config value storage

## Step 2: Setup docker compose

Create a directory named `docker_service_configs`(Give name what is ideal)
    - This will store the configuration of each docker service.

Services
    - Keycloak
        - docker_service_configs/keycloak/realm.json: 
            - Create a realm named `enterprise-search-realm`
            - Create a client named `api-client`
        
