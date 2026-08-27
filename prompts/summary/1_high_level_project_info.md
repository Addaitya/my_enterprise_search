# Enterprise Search application
Creating an semantic + keywords based searh engine for company internal data.



## Key challenges
- The data is spread across the multiple sources.
- Each file have access control

Internal Data
- It can be different kinds of files
    - pdf
    - txt

## Current focus
- Create Search layer with access control list on files.
- Currently not fousing on different source to ingest data.
    - Only consider data will be ingested locally.
        - Flow is like this
            - User upload files
            - Files are chunked 
            - uploaded to opensearch
                - opensearch automatically generate embeddings to store in document.
- ACL applied on files to search on.(current permissions are viewer and onwer)
    - Key consideration is RACL
        - Admin can create roles, group and users.
        - Other users can only make serach and view files
    - Note of confusion
        - file permissions and admin permissions are different should we store it in same table or different.
- File permissions and file details are stored in opensearch each opensearch document and in postgres db.
- Keycloack 
    - Used as authentication system that provide
    - only store users, roles and group only. It don't store permissions.
- Opensearch
    - Embedding model to use: 
        - huggingface/sentence-transformers/all-MiniLM-L6-v2
    - Each Index maily store 
        - File_id
        - chunk_id
        - chunk_seq
        - meta_file_type
        - meta_file_size
        - update_at
        - uploaded_at
        - embedding: auto generated on content
        - allowed_roles: []
        - allowed_groups: []
        - object_store_path
        - ingestion_type
        - content
        - orignal_source: not applicable for local ingestion (but create in index)
    - Here search flow will be like this
        - Backend make search on behalf of user
        - opensearch get jwt info about user
        - opensearch check for jwt correctness in keycloak
        - openserach make use of DLS(document level security) to filter result based on roles and groups.
    - View file feature
        - There will be view file link in navbar.
        - Once user made a search, search results will be show. 
        - User can click on open button to open the original file.
    - Admin dashboard
        - Only accessible to admin
            - File privilages can be assigned to roles and groups
                    - opensearch
                        -  Progress indecator must be shown and for each chunk of file this change must be solved
                    - db will be updated
                    
            - Create new users, roles and groups.
                - This need to be synced into keycloak and db