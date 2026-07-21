ARG TASK_BASE_IMAGE=swarmresearch-task-base:py312
FROM ${TASK_BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple

WORKDIR /benchmark

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url="${PIP_INDEX_URL}" -r requirements.txt

COPY evaluator.py .
COPY evaluate.sh .
RUN chmod +x evaluate.sh

ENTRYPOINT ["./evaluate.sh"]
