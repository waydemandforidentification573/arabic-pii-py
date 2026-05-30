# Hugging Face Space (Docker SDK) for the apii playground.
# Pushed to the Space by .github/workflows/deploy-space.yml; HF rebuilds on push.
FROM python:3.12-slim

WORKDIR /app

# The real engine + on-device NER (onnxruntime, tokenizers, numpy, hub).
RUN pip install --no-cache-dir "apii[ner]>=0.1.0"

# Bake the int8 ONNX NER models into the image so the Space boots ready —
# no ~210 MB download on the first visitor's request. Same repo apii uses
# by default (apii/ner.py: aajil-labs-sa/arabic-pii-ner).
ENV HF_HOME=/app/.hf
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('aajil-labs-sa/arabic-pii-ner')"

# App + runtime config. HF routes traffic to $PORT (7860); bind all
# interfaces inside the container. APII_DEMO_HOSTED flips the privacy
# banner and warms the models on boot.
COPY . /app
ENV PORT=7860 \
    APII_DEMO_HOSTED=1 \
    APII_HOME=/tmp/.apii
EXPOSE 7860

CMD ["python", "server.py", "--host", "0.0.0.0", "--no-open"]
