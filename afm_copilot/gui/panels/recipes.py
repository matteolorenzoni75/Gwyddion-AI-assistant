"""
The recipes panel.

The explanation is not a tooltip here -- it fills most of the panel. That is
the point of the product: someone who does not know Gwyddion should be able to
read what a recipe will do, why, and when it is the wrong choice, before
running it on their data.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QTextBrowser, QVBoxLayout)

from afm_copilot.bridge import GwyBridge
from afm_copilot.gui.panels.base import Panel
from afm_copilot.decide import plan_for
from afm_copilot.quality import assess
from afm_copilot.correction_gate import gate_recipe
from afm_copilot.gwy_io import load_height, load_mask
from afm_copilot.ops import RECIPES, get_recipe


def _html(recipe) -> str:
    parts = [
        f"<h3 style='margin:0 0 6px 0;'>{recipe.title}</h3>",
        f"<p style='margin:0 0 8px 0;'>{recipe.purpose}</p>",
        f"<p style='margin:0 0 4px 0;'><b>Use when</b><br>{recipe.when_to_use}</p>",
        f"<p style='margin:0 0 10px 0; color:#a33a22;'><b>Avoid if</b><br>"
        f"{recipe.when_not_to_use}</p>",
        f"<p style='margin:0 0 4px 0;'><b>{len(recipe.steps)} steps</b></p>",
        "<ol style='margin:0 0 0 16px; padding:0;'>",
    ]
    for op in recipe.operations:
        parts.append(
            f"<li style='margin-bottom:8px;'><b>{op.title}</b> "
            f"<code style='color:#1d6b62;'>{op.gwy_func}</code><br>"
            f"{op.what}<br>"
            f"<i>{op.why}</i>")
        if op.caution:
            parts.append(f"<br><span style='color:#8a6206;'>Note: {op.caution}</span>")
        parts.append("</li>")
    parts.append("</ol>")
    return "".join(parts)


class RecipesPanel(Panel):
    title = "Recipes"
    area = "right"

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self.combo = QComboBox()
        for key in sorted(RECIPES):
            self.combo.addItem(f"{RECIPES[key].title}  ({key})", key)
        self.combo.currentIndexChanged.connect(self._show)
        row.addWidget(self.combo, 1)
        layout.addLayout(row)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        layout.addWidget(self.detail, 1)

        run_row = QHBoxLayout()
        self.run_selected = QPushButton("Run on selected scans")
        self.run_selected.clicked.connect(self._run)
        run_row.addWidget(self.run_selected)
        self.review_button = QPushButton("Safety diagnosis (selected scan)")
        self.review_button.clicked.connect(self._diagnose)
        run_row.addWidget(self.review_button)
        layout.addLayout(run_row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self.status)

        self._show()

    def _show(self) -> None:
        self.detail.setHtml(_html(get_recipe(self.combo.currentData())))

    # ---------------------------------------------------------- diagnosis
    def _diagnose(self) -> None:
        """Preview recommendations; deliberately does not alter the image."""
        ch = self.ctx.channel
        if ch is None:
            self.status.setText("Select and load one topography image first.")
            return
        try:
            plan = plan_for(ch)
            quality = assess(ch)
            # Physical dimensions are only a preliminary sanity check; a
            # trusted calibration must be confirmed separately.
            dimensions_plausible = bool(ch.xreal > 0 and ch.yreal > 0)
            report = gate_recipe(
                plan, quality, calibration_verified=dimensions_plausible,
                channel_role="height")
            notes = [
                f"Acquisition quality: {quality.verdict}",
                f"Recommended recipe: {plan.recipe_key}",
                "Calibration: dimensions present (NOT independently verified)",
                "Proposed operation safety:",
            ]
            for operation in report["operations"]:
                notes.append(f"  {operation['operation']}: "
                             f"{operation['status']} — {operation['reason']}")
            notes.append("No operation has been executed by this diagnosis.")
            self.detail.setPlainText("\n".join(notes))
            self.status.setText("Diagnosis only. Review all changes before approval.")
        except (ValueError, OSError, RuntimeError) as error:
            self.status.setText(f"Cannot diagnose scan: {error}")

    # --------------------------------------------------------------- run
    def _run(self) -> None:
        scans = getattr(self.window(), "scans_panel", None)
        paths = scans.selected_paths() if scans else []
        if not paths:
            self.status.setText("Select one or more scans in the Scans panel first.")
            return

        recipe = get_recipe(self.combo.currentData())
        out = self.ctx.work_dir / "processed"
        self.run_selected.setEnabled(False)
        self.status.setText(f"Running '{recipe.key}' on {len(paths)} scan(s)...")

        self.ctx.runner.submit(
            f"Recipe '{recipe.key}' on {len(paths)} scan(s)",
            self._do_run, recipe, paths, out,
            on_result=self._done,
            on_started=self.ctx.log,
            on_failed=self._failed,
            on_progress=self.ctx.log,
        )

    def _do_run(self, recipe, paths: list[Path], out: Path) -> dict:
        bridge = GwyBridge()
        gwy = [p for p in paths if p.suffix.lower() == ".gwy"]
        raw = [p for p in paths if p.suffix.lower() != ".gwy"]
        if raw:
            report = bridge.convert_raw(raw, out / "_gwy")
            gwy.extend(Path(r["gwy"]) for r in report["results"] if r["ok"])
        # A visual veto has to constrain the execution path, not merely appear
        # in a note.  It may be overruled only by concrete operator evidence:
        # a mask saved with the reviewed .gwy file.
        for path in gwy:
            review = self.ctx.review_for(path.stem)
            if review is None or not review.restricts_automatic_masking:
                continue
            channel = load_height(path)
            plan = plan_for(
                channel,
                operator_mask=load_mask(path, channel),
                morphology_review=review,
            )
            if recipe.key != plan.recipe_key:
                raise ValueError(
                    f"{path.name} has a restrictive morphology review. "
                    f"The permitted recipe is '{plan.recipe_key}', not "
                    f"'{recipe.key}'. Change the review or export an "
                    "operator-approved mask first.")
        return bridge.run_recipe(recipe, sorted(set(gwy)), out / "processed")

    def _done(self, result: dict) -> None:
        self.run_selected.setEnabled(True)
        self.status.setText(
            f"Processed {result['n_ok']}/{result['n_total']}. "
            f"Output in {self.ctx.work_dir / 'processed' / 'processed'}")

        for rec in result["results"]:
            if not rec["ok"]:
                self.ctx.log(f"  {rec['stem']}: FAILED -- {rec['error']}")
                continue
            self.ctx.log(f"  {rec['stem']}: RMS {rec['initial']['rms']:.4g} "
                         f"-> {rec['final']['rms']:.4g} m")
            for step in rec["steps"]:
                if step["applied"] and "rms_change_percent" in step:
                    self.ctx.log(f"      {step['title']:<34} "
                                 f"{step['rms_change_percent']:+7.2f}% RMS")
                elif step["note"]:
                    self.ctx.log(f"      {step['title']:<34} {step['note']}")
        self.ctx.log("A large RMS drop is not automatically good -- levelling "
                     "removes real roughness too.")

        # Show the first result so the effect is visible immediately.
        done = [r for r in result["results"] if r["ok"]]
        if done:
            path = Path(done[0]["output"])
            try:
                self.ctx.set_channel(load_height(path), path)
            except (ValueError, OSError) as exc:
                self.ctx.log(f"Could not display the result: {exc}")

    def _failed(self, description: str, message: str) -> None:
        self.run_selected.setEnabled(True)
        self.status.setText(f"Failed: {message}")
        self.ctx.log(f"{description} failed: {message}")
