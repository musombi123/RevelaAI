def scripture_lookup_schema(question, found, occurrences, explanation):
    return {
        "type": "scripture_lookup",
        "question": question,
        "found": found,
        "occurrences": occurrences,
        "explanation": explanation
    }
