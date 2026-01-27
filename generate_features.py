import os
import re

FEATURES_DIR = "features"

TEMPLATE = '''"""
AUTO-GENERATED FEATURE MODULE
Source: {source_file}

DO NOT EDIT MANUALLY.
"""

class {class_name}:
    def __init__(self):
        pass

    def run(self, input_text: str) -> dict:
        """
        Main execution method for this feature.
        """
        return {{
            "feature": "{feature_name}",
            "status": "active",
            "message": "Feature logic not yet implemented.",
            "input": input_text
        }}
'''


def md_to_class_name(filename: str) -> str:
    name = re.sub(r"^\d+_", "", filename)
    name = name.replace(".md", "")
    return "".join(word.capitalize() for word in name.split("_"))


def main():
    for file in os.listdir(FEATURES_DIR):
        if not file.endswith(".md"):
            continue

        class_name = md_to_class_name(file)
        py_name = file.replace(".md", ".py").split("_", 1)[-1]

        py_path = os.path.join(FEATURES_DIR, py_name)
        md_path = os.path.join(FEATURES_DIR, file)

        if os.path.exists(py_path):
            print(f"⏭️ Skipped (already exists): {py_name}")
            continue

        with open(py_path, "w", encoding="utf-8") as f:
            f.write(
                TEMPLATE.format(
                    source_file=file,
                    class_name=class_name,
                    feature_name=class_name
                )
            )

        print(f"✅ Generated: {py_name}")

    print("\n🚀 Feature generation complete.")


if __name__ == "__main__":
    main()
