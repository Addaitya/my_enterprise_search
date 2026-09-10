# Ingestion pipeline

A Multi-connector pipeline that connects to different data sources.

Data Sources
- Sharepoint
- Google drive
- S3 bucket(or minio)



## Tech stack

- Airbyte 
    - collect data from different source and dump into minio(s3 bucket). 
    - Every n minute airbyte to check for updates in data in source to ingest
    - Same file could be re-updated
- Kafka
    - to create events for start complete ingestion pipeline.
- Spark and tika
    - For document processing and cluster creation
- s3 bucket(minio)
    - Used as data lake (dump everything here and later process it)


File type varity that can be ingested must increase significantly.

## Flow

- A new file added into sharepoint
- In regular update checks, airbyte get to know new file added. It dumps into s3 bucket  
- Some how event added into kafka to start data processing.
- From here spark and tika start processing. Create final chunks and dumpt it into s3 bucekt.
- Event added to push data to opensearch.
- File details must be updated into db but it must also contain the object file path (this files will be viewed to final user.)
- Chunks are extracted from s3 bucket and pushed to opensearch.



## Key question
- Can we make airbyte ingestion event based?
- Should we directly add files into minio bucket that we are goint ot show to end-user in the current project or keep it different?
- Could we use kafka as message queue refencing file path in s3 bucket
- Is this flow right verify it.
- Should we create separate server for ingestion pipeline or keep adding into same backend created?

## Tasks
- Analyse the ingestion pipeline architecture. Use web-search to if required.
- Get to know where requirement is not clear.
- Create a proper proposal here assume some requirement yourself and propose solution(it must be mentioned with requirement confusion point)