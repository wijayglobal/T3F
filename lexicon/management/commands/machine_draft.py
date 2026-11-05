import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Count

from lexicon.models import SourceKind, Status, Suggestion, Term

MODEL_DIR = "data_raw/nllb-ct2"
LABEL = "NLLB-200 machine draft (unreviewed)"


class Command(BaseCommand):
    help = "Write unreviewed Tamil drafts for English terms that have none (NLLB-200 via CTranslate2). Resumable."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=2000)
        parser.add_argument("--batch", type=int, default=64)
        parser.add_argument("--model-dir", default=MODEL_DIR)

    def handle(self, limit, batch, model_dir, **opts):
        import ctranslate2
        import sentencepiece as spm

        sp = spm.SentencePieceProcessor(str(Path(model_dir) / "sentencepiece.bpe.model"))
        tr = ctranslate2.Translator(model_dir, device="cpu", inter_threads=2, intra_threads=5)

        pool = list(
            Term.objects.annotate(n=Count("suggestions")).filter(n=0).values_list("id", "text", "gloss")
        )
        # skip tiny tokens (abbreviations transliterate badly); most frequent English words first
        pool = [r for r in pool if len(r[1]) >= 3]
        from wordfreq import zipf_frequency

        pool.sort(key=lambda r: (-zipf_frequency(r[1], "en"), r[1]))
        pool = pool[:limit]
        self.stdout.write(f"drafting {len(pool)} of the terms without Tamil")

        t0, done = time.time(), 0
        for i in range(0, len(pool), batch):
            chunk = pool[i : i + batch]
            src = [["eng_Latn"] + sp.encode(text, out_type=str) + ["</s>"] for _, text, _ in chunk]
            res = tr.translate_batch(
                src, target_prefix=[["tam_Taml"]] * len(src), beam_size=4, max_decoding_length=40
            )
            rows = []
            for (tid, text, gloss), r in zip(chunk, res):
                toks = r.hypotheses[0]
                toks = toks[1:] if toks and toks[0] == "tam_Taml" else toks
                ta = sp.decode(toks).strip()
                if ta and ta.lower() != text and any("஀" <= c <= "௿" for c in ta):
                    rows.append(
                        Suggestion(
                            term_id=tid, tamil=ta[:200], source=LABEL, source_kind=SourceKind.MACHINE, status=Status.DRAFT, license="machine output",
                            note=f"English meaning: {gloss}" if gloss else "",
                        )
                    )
            Suggestion.objects.bulk_create(rows, ignore_conflicts=True)
            done += len(chunk)
            rate = done / (time.time() - t0)
            self.stdout.write(f"  {done}/{len(pool)}  {rate:.1f} words/s")
