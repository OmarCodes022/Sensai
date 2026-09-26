FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y git-core openssh-clients && dnf clean all
COPY mirror.py ${LAMBDA_TASK_ROOT}/mirror.py
CMD ["mirror.handler"]
