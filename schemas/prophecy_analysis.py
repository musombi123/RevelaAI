def prophecy_analysis_schema(prophecy, status, interpretations, timeline_notes):
    return {
        "type": "prophecy_analysis",
        "prophecy": prophecy,
        "status": status,
        "interpretations": interpretations,
        "timeline_notes": timeline_notes
    }
