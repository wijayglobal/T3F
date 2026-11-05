"""Upload the exported dataset folder to a Hugging Face dataset repo.

    HF_TOKEN=hf_xxx manage.py push_hf --repo yourname/kalaichol [--dir export] [--private]
"""
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--repo", required=True)
        parser.add_argument("--dir", default="export")
        parser.add_argument("--private", action="store_true")

    def handle(self, repo, dir, private, **opts):
        token = os.environ.get("HF_TOKEN")
        if not token:
            raise CommandError("Set HF_TOKEN (a write token) in the environment.")
        from huggingface_hub import HfApi

        api = HfApi(token=token)
        api.create_repo(repo, repo_type="dataset", private=private, exist_ok=True)
        api.upload_folder(folder_path=dir, repo_id=repo, repo_type="dataset", commit_message="Sync from Kalaichol")
        self.stdout.write(self.style.SUCCESS(f"pushed {dir}/ -> https://huggingface.co/datasets/{repo}"))
