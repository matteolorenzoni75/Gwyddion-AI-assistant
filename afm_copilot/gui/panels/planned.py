"""
The slots that are not filled yet.

These appear in the window, disabled, saying what they will do. Showing the
shape of what is coming is more useful than hiding it: it tells you where a
feature will live, and it keeps the layout honest about what the tool does and
does not do today.

Filling one in means giving it a `build()` and setting `available = True`.
Nothing else changes -- not the window, not the other panels.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QTextBrowser,
                               QVBoxLayout, QWidget)

from afm_copilot.decide import plan_for
from afm_copilot.feedback import record_feedback, feedback_counts
from afm_copilot.gui.panels.base import Panel
from afm_copilot.gwy_io import load_height, load_mask, save_height
from afm_copilot.mask_proposals import propose as propose_masks
from afm_copilot.morphology import MorphologyReview, upsert_review


class RoughnessPanel(Panel):
    title = "Roughness"
    area = "right"
    available = False
    unavailable_reason = (
        "Roughness and spatial length.\n\n"
        "Will report Sa, Sq and the ISO 25178 family, fit the power spectral "
        "density to recover correlation length and fractal dimension, and pool "
        "several surfaces into one answer.\n\n"
        "It will also report the levelling bias: every flattening step lowers "
        "measured roughness by a calculable amount, so a raw Sq quoted after "
        "processing is always an underestimate. Getting that right is the "
        "reason this panel is not a simple standard-deviation readout."
    )


class DetectorsPanel(Panel):
    title = "Artifacts"
    area = "right"
    available = False
    unavailable_reason = (
        "Automatic artifact detection.\n\n"
        "Will name what is wrong with a scan before anything is done to it: "
        "residual tilt and bow, row banding, scars, spikes, and periodic noise "
        "at any angle -- then recommend a recipe and say why.\n\n"
        "The hard part is telling genuine periodic structure from periodic "
        "noise. The 500-sample synthetic set already carries that label, "
        "including 81 scans that contain both at once, so the detector can be "
        "tested against known answers rather than judged by eye."
    )


class LearningPanel(Panel):
    title = "Review & masks"
    area = "right"
    available = True

    _FAMILIES = (
        ("No semantic assertion", ""),
        ("Continuous granular surface", "granular_continuous"),
        ("Isolated objects", "isolated_objects"),
        ("Terraces / flat domains", "terraces"),
        ("Pores", "pores"),
        ("Fibres", "fibres"),
        ("Periodic morphology", "periodic"),
        ("Uncertain", "uncertain"),
    )

    def build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.current = QLabel("Select one scan to review")
        self.current.setWordWrap(True)
        layout.addWidget(self.current)

        form = QFormLayout()
        self.family = QComboBox()
        for label, value in self._FAMILIES:
            self.family.addItem(label, value)
        form.addRow("Morphology", self.family)
        self.effect = QComboBox()
        self.effect.addItem("Advisory — record only", "advisory")
        self.effect.addItem("Restrict — permit less processing", "restrict")
        form.addRow("Effect", self.effect)
        layout.addLayout(form)

        layout.addWidget(QLabel("Visible evidence (one observation per line)"))
        self.evidence = QPlainTextEdit()
        self.evidence.setPlaceholderText(
            "e.g. texture fills the field\nno broad flat background is visible")
        self.evidence.setMaximumHeight(90)
        layout.addWidget(self.evidence)

        plan_row = QHBoxLayout()
        self.plan_btn = QPushButton("Preview guarded plan")
        self.plan_btn.clicked.connect(self._preview)
        plan_row.addWidget(self.plan_btn)
        self.save_btn = QPushButton("Save review")
        self.save_btn.clicked.connect(self._save)
        plan_row.addWidget(self.save_btn)
        layout.addLayout(plan_row)

        layout.addWidget(QLabel("Operator feedback (private; does not train a model)"))
        self.feedback_verdict = QComboBox()
        self.feedback_verdict.addItem("Uncertain (record, not a training label)", "uncertain")
        self.feedback_verdict.addItem("Confirmed morphology", "confirmed")
        self.feedback_verdict.addItem("Rejected morphology", "rejected")
        layout.addWidget(self.feedback_verdict)
        self.training_consent = QCheckBox(
            "This is a reviewed TRAINING scan (not blind/test)")
        layout.addWidget(self.training_consent)
        self.feedback_btn = QPushButton("Record operator feedback privately")
        self.feedback_btn.clicked.connect(self._record_training_feedback)
        layout.addWidget(self.feedback_btn)

        mask_row = QHBoxLayout()
        self.masks_btn = QPushButton("Generate mask candidates")
        self.masks_btn.clicked.connect(self._generate_masks)
        mask_row.addWidget(self.masks_btn)
        self.view_masks_btn = QPushButton("View candidates")
        self.view_masks_btn.setEnabled(False)
        self.view_masks_btn.clicked.connect(self._show_masks)
        mask_row.addWidget(self.view_masks_btn)
        layout.addLayout(mask_row)

        self.candidate = QComboBox()
        self.candidate.setEnabled(False)
        layout.addWidget(self.candidate)
        self.use_candidate = QCheckBox(
            "Use selected candidate as an operator mask in plan preview")
        self.use_candidate.setEnabled(False)
        layout.addWidget(self.use_candidate)
        self.export_mask_btn = QPushButton("Export approved mask as a new .gwy")
        self.export_mask_btn.setEnabled(False)
        self.export_mask_btn.clicked.connect(self._export_mask)
        layout.addWidget(self.export_mask_btn)

        self.result = QTextBrowser()
        self.result.setPlaceholderText(
            "The proposed recipe and its reasons appear here. Nothing is "
            "processed from this panel.")
        layout.addWidget(self.result, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self.status)

        self._manifest: dict | None = None
        self._review_dialog: QDialog | None = None
        self.ctx.on_channel_changed(self._channel_changed)

    def _channel_changed(self, _channel, path: Path | None) -> None:
        stem = path.stem if path else "current scan"
        self.current.setText(f"Reviewing: {stem}")
        self._manifest = None
        self.training_consent.setChecked(False)
        self.candidate.clear()
        self.candidate.setEnabled(False)
        self.use_candidate.setChecked(False)
        self.use_candidate.setEnabled(False)
        self.view_masks_btn.setEnabled(False)
        self.export_mask_btn.setEnabled(False)
        existing = self.ctx.review_for(stem)
        if existing is None:
            self.family.setCurrentIndex(0)
            self.effect.setCurrentIndex(0)
            self.evidence.clear()
            return
        index = self.family.findData(existing.family)
        self.family.setCurrentIndex(max(0, index))
        effect_index = self.effect.findData(existing.effect)
        self.effect.setCurrentIndex(max(0, effect_index))
        self.evidence.setPlainText("\n".join(existing.evidence))
        self.status.setText("Loaded the saved review for this scan.")

    def _review(self) -> MorphologyReview | None:
        family = self.family.currentData()
        if not family or self.ctx.channel_path is None:
            return None
        evidence = tuple(line.strip() for line in self.evidence.toPlainText().splitlines()
                         if line.strip())
        return MorphologyReview(
            scan=self.ctx.channel_path.stem,
            family=family,
            effect=self.effect.currentData(),
            source="gui-operator",
            evidence=evidence,
        )

    def _selected_mask(self):
        if not self.use_candidate.isChecked() or not self.candidate.currentData():
            return None
        path = Path(self.candidate.currentData())
        return load_mask(path, load_height(path))

    def _preview(self) -> None:
        if self.ctx.channel is None:
            self.status.setText("Select a scan first.")
            return
        review = self._review()
        if review is not None:
            self.ctx.set_review(review)
        self.plan_btn.setEnabled(False)
        self.status.setText("Measuring the guarded plan...")
        self.ctx.runner.submit(
            "Guarded morphology plan",
            plan_for, self.ctx.channel,
            operator_mask=self._selected_mask(), morphology_review=review,
            on_result=self._plan_ready,
            on_failed=self._failed,
            on_progress=self.ctx.log,
        )

    def _plan_ready(self, plan) -> None:
        self.plan_btn.setEnabled(True)
        source = plan.morphology_review_source or "numerical pipeline only"
        self.result.setPlainText(
            plan.explain() + "\n\nAudit\n"
            f"review source: {source}\n"
            f"semantic restriction: {'yes' if plan.morphology_restricted else 'no'}\n"
            f"operator mask: {'yes' if plan.operator_mask is not None else 'no'}")
        self.status.setText(
            f"Preview only. Permitted recipe: {plan.recipe_key}. No height "
            "data was changed.")

    def _save(self) -> None:
        review = self._review()
        if review is None:
            self.status.setText("Choose a morphology before saving a review.")
            return
        destination = self.ctx.review_file
        if destination is None:
            self.status.setText("Open a scan folder before saving a review.")
            return
        try:
            upsert_review(destination, review)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Could not save the review: {exc}")
            return
        self.ctx.set_review(review)
        self.status.setText(f"Saved in {destination.name}. The source scan was untouched.")

    def _record_training_feedback(self) -> None:
        review = self._review()
        source = self.ctx.channel_path
        if review is None or source is None:
            self.status.setText("Select a scan and a morphology before recording feedback.")
            return
        try:
            outcome = record_feedback(
                source, family=review.family, effect=review.effect,
                verdict=self.feedback_verdict.currentData(),
                evidence=review.evidence,
                confirmed_training=self.training_consent.isChecked(),
            )
            counts = feedback_counts()
        except (OSError, ValueError, TypeError) as exc:
            self.status.setText(f"Feedback not recorded: {exc}")
            return
        self.training_consent.setChecked(False)
        self.status.setText(
            f"Private feedback recorded ({outcome['verdict']}); "
            f"{counts['confirmed']} confirmed feedback events. "
            "No automatic training or processing change."
        )

    def _proposal_source(self) -> Path | None:
        source = getattr(self.ctx.channel, "source", None)
        if source and Path(source).suffix.lower() == ".gwy":
            return Path(source)
        if self.ctx.channel_path and self.ctx.channel_path.suffix.lower() == ".gwy":
            return self.ctx.channel_path
        return None

    def _generate_masks(self) -> None:
        source = self._proposal_source()
        if source is None:
            self.status.setText(
                "Mask proposals need the converted .gwy copy of this scan.")
            return
        out = self.ctx.work_dir / "mask-proposals" / source.stem
        self.masks_btn.setEnabled(False)
        self.status.setText("Running independent Gwyddion mask proposals...")
        self.ctx.runner.submit(
            f"Mask proposals for {source.name}",
            propose_masks, [source], out,
            on_result=self._masks_ready,
            on_failed=self._failed,
            on_progress=self.ctx.log,
        )

    def _masks_ready(self, manifest: dict) -> None:
        self.masks_btn.setEnabled(True)
        self._manifest = manifest
        self.candidate.clear()
        for record in manifest.get("results", []):
            if not record.get("ok") or not record.get("statistics"):
                continue
            stats = record["statistics"]
            self.candidate.addItem(
                f"{record['method']} — {stats['fraction']:.1%}, "
                f"{stats['grains']} regions",
                record["output"],
            )
        available = self.candidate.count() > 0
        self.candidate.setEnabled(available)
        self.use_candidate.setEnabled(available)
        self.export_mask_btn.setEnabled(available)
        self.view_masks_btn.setEnabled(bool(manifest.get("review_image")))
        self.status.setText(
            f"Generated {manifest.get('n_masks', 0)} candidates. None is "
            "accepted automatically.")
        if manifest.get("review_image"):
            self._show_masks()

    def _show_masks(self) -> None:
        if not self._manifest or not self._manifest.get("review_image"):
            return
        pixmap = QPixmap(self._manifest["review_image"])
        if pixmap.isNull():
            self.status.setText("Could not display the candidate contact sheet.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Candidate masks — cyan is excluded from background fit")
        dialog.resize(1200, 720)
        box = QVBoxLayout(dialog)
        note = QLabel(
            "Compare boundaries with the topography. Selection is evidence, "
            "not permission to remove or interpolate material.")
        note.setWordWrap(True)
        box.addWidget(note)
        scroll = QScrollArea()
        label = QLabel()
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignCenter)
        scroll.setWidget(label)
        scroll.setWidgetResizable(False)
        box.addWidget(scroll, 1)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()
        self._review_dialog = dialog

    def _export_mask(self) -> None:
        if self.ctx.channel is None or not self.candidate.currentData():
            return
        candidate_path = Path(self.candidate.currentData())
        mask = load_mask(candidate_path, load_height(candidate_path))
        if mask is None:
            self.status.setText("The selected candidate contains no readable mask.")
            return
        stem = self.ctx.channel_path.stem if self.ctx.channel_path else "reviewed"
        start = str((self.ctx.channel_path.parent if self.ctx.channel_path else Path.cwd())
                    / f"{stem}-approved-mask.gwy")
        destination, _ = QFileDialog.getSaveFileName(
            self, "Export operator-approved mask", start,
            "Gwyddion files (*.gwy)")
        if not destination:
            return
        save_height(self.ctx.channel, Path(destination), mask=mask)
        self.status.setText(
            f"Exported {Path(destination).name}. Original data was not changed.")

    def _failed(self, description: str, message: str) -> None:
        self.plan_btn.setEnabled(True)
        self.masks_btn.setEnabled(True)
        self.status.setText(f"{description} failed: {message}")
        self.ctx.log(f"{description} failed: {message}")


PLANNED_PANELS = [RoughnessPanel, DetectorsPanel, LearningPanel]
