#!/usr/bin/env python3
"""
agent_learning_hook.py — Load and apply agent lessons before complex tasks.

Called by Claude Code before executing a multi-step task:
    1. Load relevant lessons from ~/.hermes/memory/agent_lessons.md
    2. Check for patterns matching current task (via tags/context)
    3. Apply learned patterns to task execution
    4. After task, optionally capture reasoning back to HFL

Usage (Python):
    from agent_learning_hook import load_lessons, apply_lessons
    
    lessons = load_lessons(filter_tag="debugging")
    suggestions = apply_lessons("Debug auth bug", lessons)
    # Use suggestions to inform task approach

Usage (CLI):
    python agent_learning_hook.py "Debug authentication timeout"
    python agent_learning_hook.py  # Dump all lessons
"""

from pathlib import Path
from datetime import datetime
import re
import sys


def load_lessons(filter_tag: str | None = None) -> dict[str, list[str]]:
    """
    Load lessons from ~/.hermes/memory/agent_lessons.md.
    
    Args:
        filter_tag: If set, only return lessons matching this tag (e.g., 'debugging')
    
    Returns:
        dict[tag] -> list of lessons
    """
    lessons_file = Path.home() / ".hermes" / "memory" / "agent_lessons.md"
    
    if not lessons_file.exists():
        return {}
    
    lessons = {}
    current_tag = None
    
    with open(lessons_file, "r", encoding="utf-8") as f:
        for line in f:
            # Section header like "## 2026-05-22T14:30:00"
            if line.startswith("## "):
                # Reset for new section
                continue
            
            # Tag header like "**#debugging**"
            tag_match = re.match(r"\*\*#(\w+)\*\*", line)
            if tag_match:
                current_tag = tag_match.group(1)
                if current_tag not in lessons:
                    lessons[current_tag] = []
                continue
            
            # Lesson line like "- pattern (seen 3x)"
            if current_tag and line.strip().startswith("- "):
                lesson = line.strip()[2:]  # Remove "- "
                lessons[current_tag].append(lesson)
    
    # Filter by tag if requested
    if filter_tag:
        return {filter_tag: lessons.get(filter_tag, [])}
    
    return lessons


def apply_lessons(task_description: str, lessons: dict[str, list[str]]) -> str:
    """
    Given a task and available lessons, suggest relevant patterns.
    
    Args:
        task_description: Current task (e.g., "Debug authentication module")
        lessons: Lessons dict from load_lessons()
    
    Returns:
        Markdown-formatted suggestions for the agent
    """
    if not lessons:
        return ""
    
    # Simple heuristic: check if task keywords match lesson tags
    task_lower = task_description.lower()
    suggestions = []
    
    for tag, lesson_list in lessons.items():
        # Check if tag is relevant (substring match on task keywords)
        if tag.lower() in task_lower or task_lower.find(tag.lower()) != -1:
            suggestions.append(f"\n### Lessons from #{tag}:")
            for lesson in lesson_list[:2]:  # Top 2 per tag
                suggestions.append(f"- {lesson}")
    
    if suggestions:
        return "\n".join(suggestions)
    return ""


def print_relevant_lessons(task_description: str):
    """
    Utility: print relevant lessons for the current task to stdout.
    Useful for agent decision-making before executing.
    """
    lessons = load_lessons()
    suggestions = apply_lessons(task_description, lessons)
    
    if suggestions:
        print("📚 Relevant agent lessons:")
        print(suggestions)
    else:
        print("(No prior lessons for this task type)")


# ─────────────────────────────────────────────────────────────────────────────
# CLI interface
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        print_relevant_lessons(task)
    else:
        # Just dump all lessons
        lessons = load_lessons()
        if lessons:
            print("Current agent lessons:")
            for tag, lesson_list in sorted(lessons.items()):
                print(f"\n#{tag}:")
                for lesson in lesson_list:
                    print(f"  - {lesson}")
        else:
            print("No lessons recorded yet")
