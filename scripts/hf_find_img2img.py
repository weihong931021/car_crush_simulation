import os, urllib.request, json

TOKEN = os.environ["HF_TOKEN"]
headers = {"Authorization": f"Bearer {TOKEN}"}

# 查所有 providers 的 text-to-image 和 image-to-image 支援
for task in ["text-to-image", "image-to-image"]:
    for provider in ["hf-inference", "together", "fal-ai", "replicate"]:
        url = f"https://huggingface.co/api/models?pipeline_tag={task}&inference_provider={provider}&limit=5&sort=downloads"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                models = json.loads(resp.read())
            if models:
                print(f"\n{task} / {provider} ({len(models)} models):")
                for m in models[:5]:
                    print(f"  {m['id']}")
        except Exception as e:
            print(f"{task}/{provider}: {e}")
