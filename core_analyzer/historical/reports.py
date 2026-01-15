# =============================================================================
# POLYMARKET EU AI REGULATION ANALYZER
# Module: historical/reports.py
# Purpose: Generate JSON and Markdown reports for historical testing
# =============================================================================
#
# OUTPUT STRUCTURE:
# output/historical/
# ├── cases/
# │   ├── CASE_001.json
# │   ├── CASE_002.json
# │   └── ...
# ├── aggregate_report.md
# └── run_summary.json
#
# REPORT FOCUS:
# The aggregate report emphasizes FALSE_ADMISSION cases as critical failures.
# These indicate situations where the analyzer would have allowed trading
# on a market that ultimately proved untradeable.
#
# =============================================================================

import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

from .models import CaseResult, OutcomeClassification

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Generates JSON and Markdown reports for historical test results.

    AUDIT PRINCIPLE:
    Reports must be deterministic and reproducible.
    No randomization, no sampling, no approximations.
    """

    def __init__(self, output_dir: str = "output/historical"):
        """
        Initialize the report generator.

        Args:
            output_dir: Base directory for output files (relative path)
        """
        self.output_dir = Path(output_dir)
        self.cases_dir = self.output_dir / "cases"

    def ensure_directories(self) -> None:
        """Create output directories if they don't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured directories exist: {self.output_dir}")

    def generate_all_reports(self, results: List[CaseResult]) -> Dict[str, str]:
        """
        Generate all reports for a set of results.

        Args:
            results: List of CaseResult objects

        Returns:
            Dictionary mapping report type to file path
        """
        self.ensure_directories()

        generated_files = {}

        # Generate individual case reports
        for result in results:
            case_path = self._generate_case_report(result)
            generated_files[f"case_{result.case.case_id}"] = str(case_path)

        # Generate aggregate markdown report
        aggregate_path = self._generate_aggregate_report(results)
        generated_files["aggregate_report"] = str(aggregate_path)

        # Generate run summary JSON
        summary_path = self._generate_run_summary(results)
        generated_files["run_summary"] = str(summary_path)

        return generated_files

    def _generate_case_report(self, result: CaseResult) -> Path:
        """
        Generate JSON report for a single case.

        Args:
            result: The case result to report

        Returns:
            Path to the generated file
        """
        filepath = self.cases_dir / f"{result.case.case_id}.json"

        report_data = {
            "case_id": result.case.case_id,
            "case_title": result.case.title,
            "case_description": result.case.description,
            "analysis_as_of_date": result.case.analysis_as_of_date.isoformat(),
            "hypothetical_target_date": result.case.hypothetical_target_date.isoformat(),
            "referenced_regulation": result.case.referenced_regulation,
            "synthetic_resolution_text": result.case.synthetic_resolution_text,
            "formal_timeline": result.case.formal_timeline.to_dict(),
            "known_outcome": result.case.known_outcome.value,
            "failure_explanation": result.case.failure_explanation,
            "analyzer_decision": result.analyzer_decision,
            "classification": result.classification.value,
            "blocking_criteria": result.blocking_criteria,
            "timeline_conflicts": result.timeline_conflicts,
            "risk_warnings": result.risk_warnings,
            "full_reasoning": result.full_reasoning,
            "is_critical_failure": result.is_critical_failure(),
            "generated_at": datetime.now().isoformat(),
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        logger.debug(f"Generated case report: {filepath}")
        return filepath

    def _generate_aggregate_report(self, results: List[CaseResult]) -> Path:
        """
        Generate aggregate Markdown report.

        Args:
            results: All case results

        Returns:
            Path to the generated file
        """
        filepath = self.output_dir / "aggregate_report.md"
        lines = []

        # ---------------------------------------------------------------------
        # HEADER
        # ---------------------------------------------------------------------
        lines.append("# Historical / Counterfactual Testing Report")
        lines.append("")
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(f"**Report Generated:** {datetime.now().isoformat()}")
        lines.append(f"**Total Cases Evaluated:** {len(results)}")
        lines.append("")

        # ---------------------------------------------------------------------
        # CLASSIFICATION COUNTS
        # ---------------------------------------------------------------------
        counts = self._count_classifications(results)

        lines.append("### Classification Summary")
        lines.append("")
        lines.append("| Classification | Count | Description |")
        lines.append("|----------------|-------|-------------|")
        lines.append(f"| CORRECT_REJECTION | {counts.get('CORRECT_REJECTION', 0)} | "
                     "Analyzer rejected, outcome was NO (correct) |")
        lines.append(f"| SAFE_PASS | {counts.get('SAFE_PASS', 0)} | "
                     "Analyzer rejected, outcome was YES (conservative) |")
        lines.append(f"| FALSE_ADMISSION | {counts.get('FALSE_ADMISSION', 0)} | "
                     "Analyzer accepted, outcome was NO (FAILURE) |")
        lines.append(f"| RARE_SUCCESS | {counts.get('RARE_SUCCESS', 0)} | "
                     "Analyzer accepted, outcome was YES (rare) |")
        lines.append("")

        # ---------------------------------------------------------------------
        # DISCIPLINE SCORE
        # ---------------------------------------------------------------------
        total = len(results)
        correct = counts.get('CORRECT_REJECTION', 0) + counts.get('RARE_SUCCESS', 0)
        conservative = counts.get('SAFE_PASS', 0)
        failures = counts.get('FALSE_ADMISSION', 0)

        if total > 0:
            discipline_rate = (correct + conservative) / total * 100
            failure_rate = failures / total * 100
        else:
            discipline_rate = 0.0
            failure_rate = 0.0

        lines.append("### Discipline Metrics")
        lines.append("")
        lines.append(f"- **Discipline Rate:** {discipline_rate:.1f}% "
                     "(CORRECT_REJECTION + SAFE_PASS + RARE_SUCCESS)")
        lines.append(f"- **Failure Rate:** {failure_rate:.1f}% (FALSE_ADMISSION)")
        lines.append(f"- **Conservative Rejections:** {conservative} (acceptable)")
        lines.append("")

        # Alert if any failures
        if failures > 0:
            lines.append("> **[!] CRITICAL:** FALSE_ADMISSION cases detected. "
                         "Review required.")
            lines.append("")

        # ---------------------------------------------------------------------
        # FALSE_ADMISSION CASES (CRITICAL)
        # ---------------------------------------------------------------------
        false_admissions = [r for r in results if r.is_critical_failure()]

        lines.append("---")
        lines.append("")
        lines.append("## FALSE_ADMISSION Cases (Critical Failures)")
        lines.append("")

        if false_admissions:
            lines.append("These cases represent structural failures where the analyzer "
                         "would have allowed trading on a market that ultimately proved "
                         "impossible or incorrect.")
            lines.append("")

            for i, fa in enumerate(false_admissions, 1):
                lines.append(f"### {i}. {fa.case.case_id}: {fa.case.title}")
                lines.append("")
                lines.append(f"**Regulation:** {fa.case.referenced_regulation}")
                lines.append("")
                lines.append(f"**Target Date:** {fa.case.hypothetical_target_date}")
                lines.append("")
                lines.append(f"**Analysis Date:** {fa.case.analysis_as_of_date}")
                lines.append("")
                lines.append(f"**Known Outcome:** {fa.case.known_outcome.value}")
                lines.append("")
                lines.append(f"**Failure Explanation:** {fa.case.failure_explanation or 'Not provided'}")
                lines.append("")
                lines.append("**Analyzer Reasoning:**")
                lines.append(f"> {fa.full_reasoning[:500]}...")
                lines.append("")
                if fa.timeline_conflicts:
                    lines.append("**Timeline Conflicts Detected:**")
                    for conflict in fa.timeline_conflicts:
                        lines.append(f"- {conflict}")
                    lines.append("")
                if fa.risk_warnings:
                    lines.append("**Risk Warnings Generated:**")
                    for warning in fa.risk_warnings:
                        lines.append(f"- {warning}")
                    lines.append("")
                lines.append("---")
                lines.append("")
        else:
            lines.append("**No FALSE_ADMISSION cases detected.** ")
            lines.append("The analyzer correctly rejected all markets that ultimately failed.")
            lines.append("")

        # ---------------------------------------------------------------------
        # ALL CASES SUMMARY TABLE
        # ---------------------------------------------------------------------
        lines.append("## All Cases Summary")
        lines.append("")
        lines.append("| Case ID | Title | Decision | Outcome | Classification |")
        lines.append("|---------|-------|----------|---------|----------------|")

        for result in results:
            case_id = result.case.case_id
            title = result.case.title[:40] + "..." if len(result.case.title) > 40 else result.case.title
            decision = result.analyzer_decision
            outcome = result.case.known_outcome.value
            classification = result.classification.value

            # Highlight failures
            if result.is_critical_failure():
                classification = f"**{classification}**"

            lines.append(f"| {case_id} | {title} | {decision} | {outcome} | {classification} |")

        lines.append("")

        # ---------------------------------------------------------------------
        # RECURRING FAILURE PATTERNS
        # ---------------------------------------------------------------------
        lines.append("## Recurring Failure Patterns")
        lines.append("")

        if false_admissions:
            patterns = self._analyze_failure_patterns(false_admissions)
            if patterns:
                for pattern, count in patterns.items():
                    lines.append(f"- **{pattern}:** {count} occurrence(s)")
                lines.append("")
            else:
                lines.append("No recurring patterns identified.")
                lines.append("")
        else:
            lines.append("No failures to analyze for patterns.")
            lines.append("")

        # ---------------------------------------------------------------------
        # METHODOLOGY NOTE
        # ---------------------------------------------------------------------
        lines.append("---")
        lines.append("")
        lines.append("## Methodology")
        lines.append("")
        lines.append("This report evaluates **analyzer discipline**, not profitability.")
        lines.append("")
        lines.append("**Key principles:**")
        lines.append("- Analyzer received ONLY information available at analysis date")
        lines.append("- NO historical prices or probabilities were used")
        lines.append("- NO hindsight signals were included")
        lines.append("- Classification is based on post-hoc comparison only")
        lines.append("")
        lines.append("**Interpretation:**")
        lines.append("- FALSE_ADMISSION is a structural failure - analyzer allowed a bad trade")
        lines.append("- SAFE_PASS is acceptable conservatism - missed opportunity, no loss")
        lines.append("- CORRECT_REJECTION is ideal - protected against a bad trade")
        lines.append("- RARE_SUCCESS is good but rare - found a valid edge")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("*This report was generated by the Historical Testing Module.*")
        lines.append("*No prices, volumes, or probabilities were used in this analysis.*")

        # Write file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Generated aggregate report: {filepath}")
        return filepath

    def _generate_run_summary(self, results: List[CaseResult]) -> Path:
        """
        Generate JSON summary of the run.

        Args:
            results: All case results

        Returns:
            Path to the generated file
        """
        filepath = self.output_dir / "run_summary.json"

        counts = self._count_classifications(results)
        total = len(results)

        summary = {
            "generated_at": datetime.now().isoformat(),
            "total_cases": total,
            "classification_counts": counts,
            "discipline_rate": (
                (counts.get('CORRECT_REJECTION', 0) +
                 counts.get('SAFE_PASS', 0) +
                 counts.get('RARE_SUCCESS', 0)) / total * 100
                if total > 0 else 0.0
            ),
            "failure_rate": (
                counts.get('FALSE_ADMISSION', 0) / total * 100
                if total > 0 else 0.0
            ),
            "false_admission_cases": [
                r.case.case_id for r in results if r.is_critical_failure()
            ],
            "correct_rejection_cases": [
                r.case.case_id for r in results
                if r.classification == OutcomeClassification.CORRECT_REJECTION
            ],
            "safe_pass_cases": [
                r.case.case_id for r in results
                if r.classification == OutcomeClassification.SAFE_PASS
            ],
            "rare_success_cases": [
                r.case.case_id for r in results
                if r.classification == OutcomeClassification.RARE_SUCCESS
            ],
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"Generated run summary: {filepath}")
        return filepath

    def _count_classifications(self, results: List[CaseResult]) -> Dict[str, int]:
        """Count results by classification."""
        counts: Dict[str, int] = {}
        for result in results:
            key = result.classification.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _analyze_failure_patterns(
        self, failures: List[CaseResult]
    ) -> Dict[str, int]:
        """
        Analyze recurring patterns in FALSE_ADMISSION cases.

        Args:
            failures: List of FALSE_ADMISSION case results

        Returns:
            Dictionary of pattern descriptions and counts
        """
        patterns: Dict[str, int] = {}

        for failure in failures:
            # Check for timeline-related patterns
            if any("timeline" in c.lower() for c in failure.timeline_conflicts):
                patterns["Timeline misassessment"] = \
                    patterns.get("Timeline misassessment", 0) + 1

            # Check for institutional constraint misses
            if any("institutional" in c.lower() for c in failure.timeline_conflicts):
                patterns["Institutional constraint missed"] = \
                    patterns.get("Institutional constraint missed", 0) + 1

            # Check for resolution ambiguity
            if not failure.blocking_criteria:
                patterns["No blocking criteria triggered"] = \
                    patterns.get("No blocking criteria triggered", 0) + 1

            # Check failure explanations for common themes
            explanation = (failure.case.failure_explanation or "").lower()
            if "delay" in explanation:
                patterns["Unexpected delays"] = \
                    patterns.get("Unexpected delays", 0) + 1
            if "application" in explanation and "adoption" in explanation:
                patterns["Application vs adoption confusion"] = \
                    patterns.get("Application vs adoption confusion", 0) + 1
            if "delegated" in explanation:
                patterns["Delegated act dependency"] = \
                    patterns.get("Delegated act dependency", 0) + 1

        return patterns
