"""Curated, defensive reverse-engineering and security curriculum for RevelaAI.

Course content is static and reviewed with a defensive-lab scope. Lab instructions
are designed for owned assets or intentionally vulnerable local training targets.
No course endpoint executes binaries, payloads, scans, or user-submitted code.
"""

from __future__ import annotations

COURSES = [
    {
        "id": "reverse-engineering-foundations",
        "title": "Reverse Engineering Foundations",
        "subtitle": "Learn to inspect compiled software without confusing evidence with assumptions.",
        "category": "Reverse Engineering",
        "level": "Beginner",
        "duration_minutes": 90,
        "description": "Build the workflow used by reverse engineers: authorization, evidence preservation, file identification, static inspection, and defensible technical notes.",
        "outcomes": [
            "Define a written assessment scope before touching an artifact.",
            "Identify common executable and package formats.",
            "Preserve provenance and calculate a SHA-256 digest.",
            "Explain the limits of static inspection and decompilation.",
        ],
        "tags": ["methodology", "file formats", "evidence", "static analysis"],
        "lessons": [
            {
                "id": "scope-and-evidence",
                "title": "Scope, authorization, and evidence handling",
                "duration_minutes": 20,
                "summary": "Set the rules of engagement and preserve the original artifact.",
                "sections": [
                    {
                        "heading": "Start with authorization",
                        "body": "Reverse engineering is a method, not permission. Before analysis, record who owns the software, who authorized the work, which exact versions and devices are in scope, what data may be inspected, and what actions are prohibited. If ownership or authorization is unclear, stop and obtain written permission.",
                        "key_points": [
                            "Prefer software you wrote, built, or were explicitly authorized to assess.",
                            "Keep third-party production systems and user data outside the lab.",
                            "Define a stop condition and a responsible reviewer.",
                        ],
                    },
                    {
                        "heading": "Preserve the evidence",
                        "body": "Keep an untouched original, work from a copy, record the acquisition source and timestamp, and calculate a SHA-256 digest. A matching digest helps show that two files are byte-for-byte identical. A hash does not prove that a file is safe, trustworthy, or benign.",
                        "key_points": [
                            "Record the file name, size, hash, source, time, and tool versions.",
                            "Keep notes and derived artifacts separate from the original.",
                            "Redact secrets and personal data from reports.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Create an evidence record for a file you own",
                    "environment": "A local folder containing a small program, test APK, or other non-sensitive artifact that you created.",
                    "steps": [
                        "Create a project folder with separate original, working-copy, and notes directories.",
                        "Copy your own sample into the original directory and make a working copy.",
                        "Calculate the SHA-256 digest with a trusted local hashing utility.",
                        "Record the source, file size, acquisition time, operating system, and tool version.",
                        "Recalculate the digest after copying and compare the values.",
                    ],
                    "evidence": [
                        "A short scope statement naming the asset and owner.",
                        "The original and working-copy hashes.",
                        "A note explaining what a hash can and cannot establish.",
                    ],
                    "safety": "Do not use confidential customer data or binaries obtained without permission.",
                },
            },
            {
                "id": "formats-and-triage",
                "title": "Executable formats and first-pass triage",
                "duration_minutes": 25,
                "summary": "Recognize the structure of common binaries and packages.",
                "sections": [
                    {
                        "heading": "Know the container",
                        "body": "PE is common on Windows, ELF on Linux and many embedded systems, Mach-O on Apple platforms, DEX inside Android packages, and WebAssembly in compatible runtimes. APK files are ZIP-based packages that can contain a manifest, DEX bytecode, resources, assets, and native libraries. Start by identifying the format and architecture before choosing an analysis tool.",
                        "key_points": [
                            "File extensions are hints; inspect file signatures and headers.",
                            "Record architecture, endianness, sections, and package contents.",
                            "Do not run an unknown file just to identify it.",
                        ],
                    },
                    {
                        "heading": "Triage before deep analysis",
                        "body": "A first-pass triage records metadata and structure without executing the artifact. It can reveal a likely format, architecture, sections, imports, exports, and package members. Treat strings and metadata as leads; they may be incomplete, misleading, or intentionally manipulated.",
                        "key_points": [
                            "Use static inspection first.",
                            "Separate observed facts from hypotheses.",
                            "Escalate only when the next step is within scope and the environment is ready.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Perform static triage on your own build",
                    "environment": "A binary or APK compiled by you. The Revela Field Kit may be used for local header inspection.",
                    "steps": [
                        "Run a file-signature or header inspection tool against the sample.",
                        "Record the detected format, architecture, file size, and available sections.",
                        "For an APK, list its manifest, DEX files, resources, and native libraries without installing it.",
                        "Write down two facts observed directly and two hypotheses that need further validation.",
                    ],
                    "evidence": [
                        "A triage table with format, architecture, size, and hash.",
                        "A clear distinction between observations and hypotheses.",
                    ],
                    "safety": "Keep triage local. Do not execute unknown binaries or extract and run unknown package contents.",
                },
            },
            {
                "id": "static-vs-dynamic",
                "title": "Static analysis, dynamic analysis, and limits",
                "duration_minutes": 25,
                "summary": "Choose an analysis method that fits the question and the risk.",
                "sections": [
                    {
                        "heading": "Static analysis",
                        "body": "Static analysis examines an artifact without running it. Typical tasks include reading headers, strings, symbols, imports, resources, bytecode, and control-flow. It is useful for understanding structure and locating code paths, but it cannot prove how every runtime path behaves.",
                        "key_points": [
                            "Disassembly represents machine instructions.",
                            "A decompiler estimates higher-level structure; it does not recover the original source exactly.",
                            "Missing symbols and compiler optimizations can make interpretation difficult.",
                        ],
                    },
                    {
                        "heading": "Dynamic analysis",
                        "body": "Dynamic analysis observes a program while it runs. It can clarify runtime behavior, but only use a disposable, isolated lab with a sample you own or are authorized to test. Use synthetic data, restrict network access, take a snapshot first, and define a cleanup plan. This course does not provide a remote execution service.",
                        "key_points": [
                            "Use a disposable VM or emulator for approved dynamic work.",
                            "Do not connect a lab sample to production accounts or real user data.",
                            "Record the environment because runtime observations are environment-dependent.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Write a method-selection note",
                    "environment": "Use the same locally built sample from the previous lesson.",
                    "steps": [
                        "Write one question that static analysis can answer reliably.",
                        "Write one runtime question that static analysis alone cannot settle.",
                        "For the runtime question, define a hypothetical isolated test environment and stop conditions.",
                        "List the evidence needed before making a security claim.",
                    ],
                    "evidence": [
                        "A short static-versus-dynamic decision record.",
                        "An isolation checklist for any future runtime experiment.",
                    ],
                    "safety": "The exercise is a planning task. Do not run samples or access third-party systems.",
                },
            },
        ],
        "quiz": [
            {
                "id": "q1",
                "question": "What does a matching SHA-256 digest establish?",
                "options": [
                    {"id": "a", "text": "That the file is safe to execute"},
                    {"id": "b", "text": "That the compared files have the same bytes"},
                    {"id": "c", "text": "That the file came from its claimed author"},
                    {"id": "d", "text": "That the file contains no vulnerabilities"},
                ],
                "answer": "b",
                "explanation": "A digest supports integrity comparison against a trusted reference. It is not a safety or authorship certificate.",
            },
            {
                "id": "q2",
                "question": "Which format is commonly used for Linux executables?",
                "options": [
                    {"id": "a", "text": "ELF"},
                    {"id": "b", "text": "PE"},
                    {"id": "c", "text": "Mach-O"},
                    {"id": "d", "text": "DEX"},
                ],
                "answer": "a",
                "explanation": "ELF is widely used for Linux executable and shared-object files.",
            },
            {
                "id": "q3",
                "question": "What should happen when asset ownership or authorization is unclear?",
                "options": [
                    {"id": "a", "text": "Run a quick scan anyway"},
                    {"id": "b", "text": "Use a stealthier test"},
                    {"id": "c", "text": "Stop and obtain explicit authorization"},
                    {"id": "d", "text": "Upload the artifact to a public analyzer"},
                ],
                "answer": "c",
                "explanation": "A defined and authorized scope is a prerequisite for responsible assessment.",
            },
            {
                "id": "q4",
                "question": "Which statement about decompilation is correct?",
                "options": [
                    {"id": "a", "text": "It always reproduces original source code exactly"},
                    {"id": "b", "text": "It is an approximation of higher-level program structure"},
                    {"id": "c", "text": "It proves that a program is harmless"},
                    {"id": "d", "text": "It is the same as running the program"},
                ],
                "answer": "b",
                "explanation": "Decompiler output is inferred from compiled code and must be checked against the underlying instructions and evidence.",
            },
        ],
        "resources": [
            {"title": "Ghidra Beginner Student Guide", "url": "https://ghidra.re/ghidra_docs/GhidraClass/Beginner/Introduction_to_Ghidra_Student_Guide.html"},
            {"title": "RevelaAI Reverse Engineering Field Notes", "url": "https://github.com/musombi123/RevelaAI/blob/main/portable/knowledge/reverse-engineering.md"},
        ],
    },
    {
        "id": "native-binary-analysis",
        "title": "Native Binary Analysis with Ghidra",
        "subtitle": "Read symbols, functions, data, and control flow in software you are authorized to inspect.",
        "category": "Binary Analysis",
        "level": "Intermediate",
        "duration_minutes": 150,
        "description": "Move from basic triage into structured static analysis of your own PE or ELF program using disassembly, decompilation, cross-references, and evidence-led notes.",
        "outcomes": [
            "Create a repeatable Ghidra project for an owned sample.",
            "Navigate functions, symbols, strings, and cross-references.",
            "Compare decompiler output with machine-level instructions.",
            "Document a defensible finding without overstating certainty.",
        ],
        "tags": ["Ghidra", "PE", "ELF", "disassembly", "control flow"],
        "lessons": [
            {
                "id": "ghidra-projects",
                "title": "Set up a Ghidra project",
                "duration_minutes": 35,
                "summary": "Import a known sample and understand the analysis workspace.",
                "sections": [
                    {
                        "heading": "Import and identify",
                        "body": "Create a non-shared project for a program you compiled yourself. Import the binary, confirm the detected format and processor language, and review the program tree. Accept automatic analysis only after confirming the target file and architecture. Keep the source file and its digest in your evidence record.",
                        "key_points": [
                            "Use a local sample that you created or have permission to inspect.",
                            "Confirm architecture rather than accepting a guess.",
                            "Save project notes alongside, not inside, the original artifact.",
                        ],
                    },
                    {
                        "heading": "Orient yourself",
                        "body": "The listing shows instructions and data; the decompiler estimates source-like pseudocode; the symbol and function views help navigate program structure. These views are complementary. A useful analysis moves between them instead of treating one panel as ground truth.",
                        "key_points": [
                            "Start from the entry point and known program functions.",
                            "Rename only when evidence supports the interpretation.",
                            "Record uncertainty when names and types are inferred.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Import your own compiled test program",
                    "environment": "A tiny program you wrote and compiled locally, with its source retained for comparison.",
                    "steps": [
                        "Create a new local Ghidra project.",
                        "Import your own executable and confirm its format and architecture.",
                        "Run the standard analysis on the sample.",
                        "Locate the entry point and at least two functions.",
                        "Save a project note listing the function addresses and why you identified them.",
                    ],
                    "evidence": [
                        "Project screenshot or exported notes.",
                        "Input hash and detected architecture.",
                    ],
                    "safety": "Do not import a third-party application unless its license and assessment scope permit analysis.",
                },
            },
            {
                "id": "symbols-and-cross-references",
                "title": "Symbols, strings, and cross-references",
                "duration_minutes": 35,
                "summary": "Use navigation evidence to understand how functions relate.",
                "sections": [
                    {
                        "heading": "Symbols and imports",
                        "body": "Symbols provide names for functions and objects when available. Imports reveal external functions a program expects to use; exports reveal functions exposed by a library. Stripped binaries may lack useful names, so combine imports, strings, function boundaries, and cross-references carefully.",
                        "key_points": [
                            "An imported API indicates a dependency, not necessarily an executed code path.",
                            "A string may be unused, stale, or intentionally misleading.",
                            "Trace references before assigning meaning to a function.",
                        ],
                    },
                    {
                        "heading": "Cross-reference reasoning",
                        "body": "Cross-references connect a string, constant, function, or data item to the places that reference it. Follow a small number of references at a time and record the chain. This helps build a call-flow hypothesis without assuming that a symbol name explains behavior.",
                        "key_points": [
                            "Follow caller and callee relationships.",
                            "Check the surrounding basic blocks and data flow.",
                            "Treat a hypothesis as provisional until corroborated.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Build a small function map",
                    "environment": "Continue with the sample you compiled yourself.",
                    "steps": [
                        "Find a harmless string that appears in your own program.",
                        "Use cross-references to locate the code that references it.",
                        "Record the function name or address and its callers.",
                        "Compare the function's decompiler view with its listing.",
                        "Write a one-paragraph explanation with confidence and limitations.",
                    ],
                    "evidence": [
                        "A call-flow diagram or function map.",
                        "A short explanation linked to addresses or screenshots.",
                    ],
                    "safety": "Do not infer or publish secrets from software you do not own.",
                },
            },
            {
                "id": "control-flow-and-decompiler",
                "title": "Control flow and decompiler validation",
                "duration_minutes": 40,
                "summary": "Interpret branches and validate pseudocode against instructions.",
                "sections": [
                    {
                        "heading": "Control-flow basics",
                        "body": "A function is composed of basic blocks linked by control-flow edges. Conditional branches select a path based on program state. Function graphs help visualize these paths and call trees help show relationships between functions. Compiler optimizations can fold, inline, or rearrange source-level constructs.",
                        "key_points": [
                            "A branch condition is meaningful only when its inputs are understood.",
                            "Optimized code may not resemble the source structure.",
                            "A reachable path is not proof that the path is exploitable.",
                        ],
                    },
                    {
                        "heading": "Validate the decompiler",
                        "body": "Use the decompiler to generate a readable hypothesis, then compare key conditions and data operations with the listing. Correct types and function signatures when evidence supports the change. Document any unresolved ambiguity rather than forcing a neat source-level story.",
                        "key_points": [
                            "Validate security-relevant branches against machine instructions.",
                            "Check signedness, bounds, and data widths.",
                            "Keep the original decompiler result in the analysis record when making annotations.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Explain one control-flow decision",
                    "environment": "Use a conditional function in your own compiled test program.",
                    "steps": [
                        "Locate a function containing a conditional branch.",
                        "View its function graph and identify the basic blocks.",
                        "Inspect the branch condition in both the listing and decompiler.",
                        "Explain what input controls the branch in your test program.",
                        "Record where compiler optimization changed the apparent source structure.",
                    ],
                    "evidence": [
                        "Annotated control-flow screenshot or notes.",
                        "A concise explanation of the branch and its limits.",
                    ],
                    "safety": "This exercise analyzes program structure; it does not involve exploit development or modification of third-party binaries.",
                },
            },
        ],
        "quiz": [
            {
                "id": "q1",
                "question": "What is the best first action after importing a native binary?",
                "options": [
                    {"id": "a", "text": "Assume the detected architecture is correct"},
                    {"id": "b", "text": "Confirm format and processor architecture"},
                    {"id": "c", "text": "Patch the entry point"},
                    {"id": "d", "text": "Run every referenced process"},
                ],
                "answer": "b",
                "explanation": "Format and architecture determine how instructions and data should be interpreted.",
            },
            {
                "id": "q2",
                "question": "What does an import table tell you?",
                "options": [
                    {"id": "a", "text": "Which external symbols a program depends on"},
                    {"id": "b", "text": "That every imported function is executed"},
                    {"id": "c", "text": "That the binary is malware"},
                    {"id": "d", "text": "The exact original source code"},
                ],
                "answer": "a",
                "explanation": "Imports indicate declared external dependencies, not runtime execution or intent.",
            },
            {
                "id": "q3",
                "question": "Why should decompiler output be checked against the listing?",
                "options": [
                    {"id": "a", "text": "Decompiler output is always encrypted"},
                    {"id": "b", "text": "Decompiler output is an inferred approximation"},
                    {"id": "c", "text": "The listing is only a screenshot"},
                    {"id": "d", "text": "The decompiler executes functions"},
                ],
                "answer": "b",
                "explanation": "Decompiler output is reconstructed from machine code and can be affected by optimization and missing metadata.",
            },
            {
                "id": "q4",
                "question": "A cross-reference is most useful for...",
                "options": [
                    {"id": "a", "text": "Proving the whole application is secure"},
                    {"id": "b", "text": "Connecting code or data to places that reference it"},
                    {"id": "c", "text": "Recovering deleted source files"},
                    {"id": "d", "text": "Authenticating the software publisher"},
                ],
                "answer": "b",
                "explanation": "Cross-references help reconstruct relationships and should be combined with additional evidence.",
            },
        ],
        "resources": [
            {"title": "Ghidra Beginner Student Guide", "url": "https://ghidra.re/ghidra_docs/GhidraClass/Beginner/Introduction_to_Ghidra_Student_Guide.html"},
            {"title": "RevelaAI Reverse Engineering Field Notes", "url": "https://github.com/musombi123/RevelaAI/blob/main/portable/knowledge/reverse-engineering.md"},
        ],
    },
    {
        "id": "android-app-reverse-engineering",
        "title": "Android App Reverse Engineering",
        "subtitle": "Audit APK structure, permissions, storage, and trust boundaries.",
        "category": "Mobile Security",
        "level": "Intermediate",
        "duration_minutes": 180,
        "description": "Understand APK internals and apply OWASP mobile testing guidance to debug builds and applications you own or are authorized to assess.",
        "outcomes": [
            "Describe the main components inside an APK.",
            "Inspect manifest declarations and exported components.",
            "Review local storage and network security configuration.",
            "Translate observations into actionable remediation tests.",
        ],
        "tags": ["Android", "APK", "JADX", "APKTool", "OWASP MASTG"],
        "lessons": [
            {
                "id": "apk-structure",
                "title": "APK anatomy and manifest review",
                "duration_minutes": 40,
                "summary": "Understand the package before opening the code.",
                "sections": [
                    {
                        "heading": "An APK is a structured package",
                        "body": "An APK commonly contains AndroidManifest.xml, DEX bytecode, resources, assets, signing metadata, and sometimes native libraries. Package triage should identify the application ID, version, minimum and target SDK, permissions, declared components, and signing information. Keep the package hash and acquisition source with your notes.",
                        "key_points": [
                            "Inspect packages you own or are authorized to assess.",
                            "Treat permissions as capability declarations that need context.",
                            "A declared component is not automatically vulnerable.",
                        ],
                    },
                    {
                        "heading": "Manifest trust boundaries",
                        "body": "Activities, services, receivers, and providers can expose entry points to other applications when exported. Review whether each exposed component needs to be public, whether permissions protect it, and whether intent data is validated. Verify the runtime behavior in an owned test build before declaring a finding.",
                        "key_points": [
                            "Review exported state and component-level permissions.",
                            "Validate deep-link and intent inputs.",
                            "Prefer the least exposure needed by the product.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Review the manifest of your own APK",
                    "environment": "A debug APK from a project you control; JADX or APKTool may be used for static inspection.",
                    "steps": [
                        "Record the package hash, application ID, version, and SDK targets.",
                        "Inspect the manifest and list declared permissions.",
                        "List exported activities, services, receivers, and providers.",
                        "For each exported component, write down the intended caller and required permission.",
                        "Propose a minimal manifest or authorization change for any unnecessary exposure.",
                    ],
                    "evidence": [
                        "A redacted manifest review table.",
                        "A list of proposed controls and regression tests.",
                    ],
                    "safety": "Do not decompile private third-party applications or attempt to access their accounts or services.",
                },
            },
            {
                "id": "dex-and-resources",
                "title": "DEX, resources, and decompiled code",
                "duration_minutes": 45,
                "summary": "Navigate decompiled output without treating it as original source.",
                "sections": [
                    {
                        "heading": "Read the application structure",
                        "body": "JADX can display Java-like code reconstructed from DEX, while APKTool decodes resources and provides a view of Smali and package structure. Neither restores the original developer project exactly. Obfuscation, optimization, Kotlin metadata, and generated code can change the output. Follow evidence across the manifest, resources, and relevant code paths.",
                        "key_points": [
                            "Use JADX for a readable code-navigation view.",
                            "Use APKTool when resource or Smali structure matters.",
                            "Validate important observations against the package and, where possible, the source project.",
                        ],
                    },
                    {
                        "heading": "Search for security-sensitive patterns",
                        "body": "In your own application, review where tokens are stored, how API endpoints are selected, how input is validated, and whether authorization decisions are made by the server. A string that looks like a key is a lead, not proof that it is active. Do not copy, use, or test credentials found in an artifact.",
                        "key_points": [
                            "Use synthetic test values in labs.",
                            "Never test discovered credentials against a real service.",
                            "Move authorization and entitlement decisions to trusted server-side code.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Trace a harmless feature in your own app",
                    "environment": "A debug APK and its corresponding source code from a project you control.",
                    "steps": [
                        "Open the APK in JADX and locate a feature label or resource you recognize.",
                        "Trace references to the relevant activity or class.",
                        "Compare the reconstructed view with the source project.",
                        "Identify one place where the app calls an API and record the server endpoint name only.",
                        "Confirm that the server, not the client, performs authorization.",
                    ],
                    "evidence": [
                        "A small feature-to-code navigation map.",
                        "A written note describing one client/server trust boundary.",
                    ],
                    "safety": "Use synthetic credentials and a development endpoint. Never probe production APIs discovered in an APK.",
                },
            },
            {
                "id": "mobile-security-controls",
                "title": "Storage, network, and platform security",
                "duration_minutes": 45,
                "summary": "Audit the mobile controls that protect user data.",
                "sections": [
                    {
                        "heading": "Local data and cryptographic design",
                        "body": "Review how the app stores session material and sensitive user data. Sensitive values should not be written to logs or ordinary preferences in plaintext. Prefer platform-backed keystore facilities and well-reviewed cryptographic APIs. Avoid inventing custom cryptography, and verify key lifecycle, backup behavior, and logout cleanup.",
                        "key_points": [
                            "Use test accounts and synthetic data.",
                            "Check debug logs and local storage after sensitive operations.",
                            "Do not hard-code secrets into the APK.",
                        ],
                    },
                    {
                        "heading": "Network and platform controls",
                        "body": "Review whether cleartext traffic is disabled where appropriate, TLS validation is correct, and deep links validate their inputs. Certificate pinning is a resilience control with operational trade-offs; test it only in an authorized debug build and document certificate rotation and recovery behavior. Do not treat any single hardening feature as a substitute for server-side authorization.",
                        "key_points": [
                            "Verify the app's network security configuration.",
                            "Use a controlled test proxy only with an owned test build and synthetic data.",
                            "Retest the backend authorization boundary independently.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Build a mobile security checklist",
                    "environment": "Your own debug build, test account, and emulator.",
                    "steps": [
                        "Inspect the network security configuration.",
                        "Review sensitive-data storage and logging in the source project.",
                        "Check deep-link inputs and exported component permissions.",
                        "Run the relevant OWASP MASTG checks that are in scope for your app.",
                        "Create a remediation checklist and a regression test for each confirmed issue.",
                    ],
                    "evidence": [
                        "A checklist mapped to mobile security controls.",
                        "A remediation entry with owner, risk, and retest criteria.",
                    ],
                    "safety": "Dynamic checks are limited to your own debug build in an emulator. No third-party app tampering is part of this lab.",
                },
            },
        ],
        "quiz": [
            {
                "id": "q1",
                "question": "What does the APK usually contain?",
                "options": [
                    {"id": "a", "text": "Only a single Java source file"},
                    {"id": "b", "text": "Manifest, DEX, resources, and possibly native libraries"},
                    {"id": "c", "text": "Only images and fonts"},
                    {"id": "d", "text": "A complete original IDE project"},
                ],
                "answer": "b",
                "explanation": "An APK is a package containing compiled code, manifest, resources, assets, and optional native libraries.",
            },
            {
                "id": "q2",
                "question": "Why is an exported Android component important to review?",
                "options": [
                    {"id": "a", "text": "It may be callable by other applications"},
                    {"id": "b", "text": "It always exposes the whole database"},
                    {"id": "c", "text": "It means the app is signed incorrectly"},
                    {"id": "d", "text": "It disables TLS"},
                ],
                "answer": "a",
                "explanation": "Exported components can form inter-application entry points and should have appropriate permissions and input validation.",
            },
            {
                "id": "q3",
                "question": "What is the safest response to a credential-like string found during analysis?",
                "options": [
                    {"id": "a", "text": "Try it against the live service"},
                    {"id": "b", "text": "Post it in a public report"},
                    {"id": "c", "text": "Treat it as sensitive, do not use it, and notify the owner"},
                    {"id": "d", "text": "Store it in a shared notes file"},
                ],
                "answer": "c",
                "explanation": "Never validate or reuse credentials discovered in an artifact. Handle the evidence as sensitive and report it through the authorized channel.",
            },
            {
                "id": "q4",
                "question": "Where should authorization decisions be enforced?",
                "options": [
                    {"id": "a", "text": "Only in a hidden mobile button"},
                    {"id": "b", "text": "Only in a client-side feature flag"},
                    {"id": "c", "text": "On the trusted server for every protected operation"},
                    {"id": "d", "text": "In the APK file name"},
                ],
                "answer": "c",
                "explanation": "Client applications are under user control. The backend must authorize every protected request.",
            },
        ],
        "resources": [
            {"title": "OWASP Mobile Application Security Testing Guide", "url": "https://mas.owasp.org/MASTG/"},
            {"title": "JADX decompiler", "url": "https://github.com/skylot/jadx"},
            {"title": "APKTool", "url": "https://apktool.org/"},
        ],
    },
    {
        "id": "web-api-reverse-engineering",
        "title": "Web and API Reverse Engineering for Defenders",
        "subtitle": "Map browser behavior to backend contracts and find trust-boundary mistakes.",
        "category": "Application Security",
        "level": "Intermediate",
        "duration_minutes": 150,
        "description": "Learn to inspect browser assets and API interactions, distinguish client-side controls from server-side enforcement, and validate fixes in an intentionally vulnerable local application.",
        "outcomes": [
            "Map a web feature across browser, API, and persistence layers.",
            "Identify security assumptions hidden in client-side code.",
            "Use an intentionally vulnerable local training app safely.",
            "Write regression tests for authorization and input-validation fixes.",
        ],
        "tags": ["browser", "API", "OWASP", "authorization", "source maps"],
        "lessons": [
            {
                "id": "browser-surface",
                "title": "Inspect the browser-side application",
                "duration_minutes": 35,
                "summary": "Understand what the browser reveals and what it cannot prove.",
                "sections": [
                    {
                        "heading": "Map the client",
                        "body": "Browser developer tools can reveal loaded scripts, network requests, storage usage, route names, feature flags, and API response shapes. Source maps can improve debugging when intentionally published, but they should not be treated as a security boundary. Keep the inspection limited to a site you own or a local training environment.",
                        "key_points": [
                            "Record the page, action, request, response, and environment.",
                            "Do not copy session tokens or personal data into notes.",
                            "Obfuscated JavaScript is still client-controlled code.",
                        ],
                    },
                    {
                        "heading": "Trace a feature end to end",
                        "body": "Choose one harmless feature in your own application. Follow its user action through the UI handler, request method and path, server route, authorization check, and data operation. This reveals where a control is enforced and whether a client assumption is being trusted by the backend.",
                        "key_points": [
                            "Trace one request at a time.",
                            "Identify the authoritative server-side decision.",
                            "Use request IDs and redacted evidence when available.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Map a feature in your development app",
                    "environment": "A local development copy of a web application you control.",
                    "steps": [
                        "Open browser developer tools and select a non-sensitive feature.",
                        "Record the UI action and corresponding API method and path.",
                        "Locate the server handler and its authorization check.",
                        "Trace the data operation without exporting tokens or personal data.",
                        "Draw the client-to-server flow and label the trust boundary.",
                    ],
                    "evidence": [
                        "A sanitized request-flow diagram.",
                        "A note identifying the server-side authorization point.",
                    ],
                    "safety": "Do not inspect accounts, endpoints, or traffic that you are not authorized to assess.",
                },
            },
            {
                "id": "trust-boundaries",
                "title": "Client-side controls and server-side authorization",
                "duration_minutes": 40,
                "summary": "Understand why hiding a button is not an access-control system.",
                "sections": [
                    {
                        "heading": "A client is not an authority",
                        "body": "A browser or mobile client runs in an environment controlled by its user. Hidden buttons, route guards, disabled form fields, and client-side role labels improve user experience but cannot authorize a protected operation. The server must derive identity from a verified credential and check permission against the requested resource on every relevant request.",
                        "key_points": [
                            "Authenticate the caller and authorize the specific action separately.",
                            "Bind resource access to the verified user or tenant.",
                            "Reject identity hints that conflict with the verified session.",
                        ],
                    },
                    {
                        "heading": "Validate object-level access",
                        "body": "For each request that reads or changes an object, verify that the caller is entitled to that exact object. Test both allowed and denied cases, including attempts to substitute another user's object identifier in a local fixture. Use synthetic records and never test another real person's account.",
                        "key_points": [
                            "Check ownership or delegated permissions at the data boundary.",
                            "Do not rely on an identifier being hard to guess.",
                            "Make denial behavior predictable and auditable.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Create a two-user authorization test",
                    "environment": "A local toy API with two synthetic users and two synthetic records.",
                    "steps": [
                        "Create user A, user B, and one record owned by each.",
                        "Write an allowed test for each owner reading their own record.",
                        "Write a denied test for user A requesting user B's record identifier.",
                        "Verify that changing a client-side role or route does not change the backend decision.",
                        "Implement or document the server-side ownership check and rerun the tests.",
                    ],
                    "evidence": [
                        "Automated allow/deny test results.",
                        "A short explanation of the object-level authorization rule.",
                    ],
                    "safety": "The scenario must use local synthetic identities and records. Do not enumerate real account identifiers.",
                },
            },
            {
                "id": "local-vulnerable-app",
                "title": "Practice with an intentionally vulnerable local app",
                "duration_minutes": 45,
                "summary": "Learn vulnerability classes in a deliberately insecure training environment.",
                "sections": [
                    {
                        "heading": "Use a purpose-built training target",
                        "body": "OWASP Juice Shop is deliberately insecure and intended for security training. Run it locally in an isolated environment and follow its official guide. The objective is to understand the vulnerability class, the violated assumption, and the defensive fix—not to transfer a challenge technique to a public service.",
                        "key_points": [
                            "Use a loopback-only or otherwise isolated lab deployment.",
                            "Keep the lab separate from production credentials and networks.",
                            "Record the lesson and remediation, not reusable attack payloads.",
                        ],
                    },
                    {
                        "heading": "Turn observations into regression tests",
                        "body": "A useful security exercise ends with a control that stays fixed. Describe the precondition, expected behavior, observed behavior, security impact, and minimum correction. Then add a test that fails before the fix and passes after it, using only the local training environment.",
                        "key_points": [
                            "Prefer minimal and reproducible test cases.",
                            "Fix the root cause rather than hiding the symptom.",
                            "Retest neighboring roles and objects to avoid regressions.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Complete a local training finding",
                    "environment": "OWASP Juice Shop running locally on your own machine, with no public exposure.",
                    "steps": [
                        "Start the official training app using its documented local setup.",
                        "Choose one beginner challenge and read its learning objective.",
                        "Identify the broken trust assumption in the local app.",
                        "Write a finding with expected and observed behavior, impact, and scope.",
                        "Propose the defensive control and a regression test; do not test the technique on another site.",
                    ],
                    "evidence": [
                        "A local-only lab note naming the vulnerability class.",
                        "A remediation proposal and regression-test outline.",
                    ],
                    "safety": "Keep the training app private to your lab. Never expose it to the public internet or reuse its challenge against real services.",
                },
            },
        ],
        "quiz": [
            {
                "id": "q1",
                "question": "Why is a hidden or disabled client-side button not sufficient authorization?",
                "options": [
                    {"id": "a", "text": "Because browser code is controlled by the user"},
                    {"id": "b", "text": "Because CSS cannot render buttons"},
                    {"id": "c", "text": "Because APIs cannot identify users"},
                    {"id": "d", "text": "Because all web requests are anonymous"},
                ],
                "answer": "a",
                "explanation": "Client-side controls can be changed. Protected actions must be authorized on the server.",
            },
            {
                "id": "q2",
                "question": "What is the correct way to test object-level authorization?",
                "options": [
                    {"id": "a", "text": "Try random production user IDs"},
                    {"id": "b", "text": "Use two synthetic users and records in a local fixture"},
                    {"id": "c", "text": "Disable the API authentication layer"},
                    {"id": "d", "text": "Publish the record identifiers"},
                ],
                "answer": "b",
                "explanation": "Synthetic local fixtures allow controlled allow/deny tests without exposing real accounts.",
            },
            {
                "id": "q3",
                "question": "What is OWASP Juice Shop designed for?",
                "options": [
                    {"id": "a", "text": "Production e-commerce hosting"},
                    {"id": "b", "text": "Security training using an intentionally vulnerable application"},
                    {"id": "c", "text": "Credential storage"},
                    {"id": "d", "text": "Deploying malware"},
                ],
                "answer": "b",
                "explanation": "Juice Shop is a deliberately insecure training application and should be kept in a controlled lab.",
            },
            {
                "id": "q4",
                "question": "What should a good vulnerability exercise produce?",
                "options": [
                    {"id": "a", "text": "Only a screenshot of an error"},
                    {"id": "b", "text": "A repeatable finding, root-cause fix, and regression test"},
                    {"id": "c", "text": "A list of live targets"},
                    {"id": "d", "text": "A way to avoid audit logging"},
                ],
                "answer": "b",
                "explanation": "A finding is useful when it is evidence-based and the correction is protected by a regression test.",
            },
        ],
        "resources": [
            {"title": "OWASP Juice Shop", "url": "https://owasp.org/www-project-juice-shop/"},
            {"title": "OWASP Web Security Testing Guide", "url": "https://owasp.org/www-project-web-security-testing-guide/"},
            {"title": "OWASP Application Security Verification Standard", "url": "https://owasp.org/www-project-application-security-verification-standard/"},
        ],
    },
    {
        "id": "firmware-iot-analysis",
        "title": "Firmware and IoT Security Analysis",
        "subtitle": "Inspect firmware safely and turn device findings into practical hardening work.",
        "category": "Embedded Security",
        "level": "Advanced",
        "duration_minutes": 180,
        "description": "Learn a static-first process for understanding firmware packages, embedded file systems, update trust, exposed services, and secure device lifecycle controls.",
        "outcomes": [
            "Record firmware provenance and hardware compatibility.",
            "Identify common firmware containers and embedded file-system indicators.",
            "Review update signing, debug interfaces, and secret-handling assumptions.",
            "Produce a safe remediation plan without flashing or actuating hardware.",
        ],
        "tags": ["firmware", "IoT", "embedded Linux", "static triage", "supply chain"],
        "lessons": [
            {
                "id": "firmware-provenance",
                "title": "Firmware provenance and package triage",
                "duration_minutes": 40,
                "summary": "Identify the image and preserve its chain of custody.",
                "sections": [
                    {
                        "heading": "Confirm the target and provenance",
                        "body": "Firmware is specific to hardware revisions, bootloaders, memory layouts, and update processes. Record the device model, board revision, vendor release, download source, and digest. Never assume that an image for a similar model is interchangeable. Use vendor documentation and a device you own or are authorized to assess.",
                        "key_points": [
                            "A filename is not proof of device compatibility.",
                            "Hash the original image and retain it unchanged.",
                            "Never flash an unknown or mismatched image as an analysis shortcut.",
                        ],
                    },
                    {
                        "heading": "Static first-pass inspection",
                        "body": "A firmware package may contain a vendor wrapper, header, compressed payload, bootloader, kernel, root file system, and configuration. Start with signatures, sizes, offsets, and known container structures. Record what the parser actually identifies and what remains unknown.",
                        "key_points": [
                            "Use read-only inspection tools and known file signatures.",
                            "Treat parser output as a hypothesis requiring validation.",
                            "Do not execute scripts or binaries found in an image.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Write a firmware intake record",
                    "environment": "A firmware package published by the device manufacturer for a device you own; static inspection only.",
                    "steps": [
                        "Record the device model, hardware revision, firmware version, and official source.",
                        "Calculate the package hash and preserve the original.",
                        "Inspect the file signature and document any recognized containers.",
                        "Record the tools and versions used and any parsing limitations.",
                        "Create a compatibility checklist before considering any maintenance operation.",
                    ],
                    "evidence": [
                        "Firmware provenance and hash record.",
                        "A static triage summary with limitations.",
                    ],
                    "safety": "Do not flash, boot, or execute the image. Do not use leaked or unauthorized firmware.",
                },
            },
            {
                "id": "embedded-trust",
                "title": "Embedded trust boundaries and update design",
                "duration_minutes": 45,
                "summary": "Review how devices authenticate updates and protect sensitive configuration.",
                "sections": [
                    {
                        "heading": "Update integrity and authenticity",
                        "body": "A secure update process should authenticate the publisher and verify image integrity before installation. Design reviews should examine signing-key protection, rollback policy, recovery behavior, and how the device handles interrupted updates. A checksum alone detects accidental corruption only when its reference is trusted; it does not authenticate the publisher.",
                        "key_points": [
                            "Use a signed update process rooted in protected trust anchors.",
                            "Define a safe rollback and recovery policy.",
                            "Separate update verification from device actuation.",
                        ],
                    },
                    {
                        "heading": "Configuration and service exposure",
                        "body": "Review your own firmware for default credentials, debug settings, unnecessary services, and sensitive configuration. Do not use any discovered credential. Record the location and risk, notify the owner, rotate or remove the secret, and add a build-time check to prevent recurrence.",
                        "key_points": [
                            "Use synthetic values in training images.",
                            "Disable production debug surfaces through documented configuration.",
                            "Restrict management interfaces and require strong authentication.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Assess update and debug controls on paper",
                    "environment": "Use vendor documentation and a device design or firmware project you control.",
                    "steps": [
                        "Draw the update path from publisher to device.",
                        "Mark where authenticity, integrity, rollback, and recovery are checked.",
                        "List debug interfaces and services that the product actually requires.",
                        "Identify one way a default secret could be prevented at build time without using or testing the secret.",
                        "Propose a test for signed update rejection and recovery behavior.",
                    ],
                    "evidence": [
                        "An update trust-boundary diagram.",
                        "A hardening checklist with verification tests.",
                    ],
                    "safety": "This is a design-review lab. Do not connect probes to unknown boards, bypass device locks, or alter live firmware.",
                },
            },
            {
                "id": "iot-reporting",
                "title": "Device hardening and responsible reporting",
                "duration_minutes": 40,
                "summary": "Translate embedded findings into changes that can be verified.",
                "sections": [
                    {
                        "heading": "Risk is more than a technical weakness",
                        "body": "A firmware finding should include the affected model and version, access prerequisites, physical or network exposure, user impact, evidence, and realistic mitigations. A debug interface on an inaccessible board and an internet-exposed management service have different risk profiles even when the weakness name is similar.",
                        "key_points": [
                            "Identify the exact affected version and deployment context.",
                            "Distinguish confirmed impact from a theoretical possibility.",
                            "Avoid publishing secrets, exploit payloads, or private device data.",
                        ],
                    },
                    {
                        "heading": "Retest the correction",
                        "body": "A useful remediation plan names the owner, change, verification procedure, and regression condition. For hardware, a qualified engineer must review electrical limits and manufacturer requirements before physical work. A software analysis course cannot authorize device actuation or firmware flashing.",
                        "key_points": [
                            "Add tests to the update pipeline where possible.",
                            "Require signed releases and traceable build provenance.",
                            "Keep physical and electrical operations under qualified review.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Produce a defensive device assessment",
                    "environment": "Use a hypothetical or authorized device project; no live device testing is required.",
                    "steps": [
                        "Write a one-page finding with the affected component and version.",
                        "State the preconditions and evidence without disclosing secrets.",
                        "Describe the business and safety impact.",
                        "Propose a fix, owner, and regression test.",
                        "List the checks that require a qualified hardware engineer.",
                    ],
                    "evidence": [
                        "A redacted technical finding.",
                        "A remediation and retest plan.",
                    ],
                    "safety": "Do not perform hardware actuation, bypass safety interlocks, or flash firmware as part of this academy lab.",
                },
            },
        ],
        "quiz": [
            {
                "id": "q1",
                "question": "Why must firmware model and hardware revision be recorded?",
                "options": [
                    {"id": "a", "text": "Firmware images are always universal"},
                    {"id": "b", "text": "Images may depend on hardware-specific layouts and bootloaders"},
                    {"id": "c", "text": "It replaces signature verification"},
                    {"id": "d", "text": "It proves the device is safe"},
                ],
                "answer": "b",
                "explanation": "Firmware compatibility is tied to the exact hardware and boot process.",
            },
            {
                "id": "q2",
                "question": "What does a checksum alone prove?",
                "options": [
                    {"id": "a", "text": "Who published the image"},
                    {"id": "b", "text": "That the image is harmless"},
                    {"id": "c", "text": "Integrity relative to a trusted reference"},
                    {"id": "d", "text": "That rollback is impossible"},
                ],
                "answer": "c",
                "explanation": "A checksum is useful for integrity comparison, but publisher authenticity requires a trusted signature process.",
            },
            {
                "id": "q3",
                "question": "What is the appropriate action after finding a credential-like value in your own firmware?",
                "options": [
                    {"id": "a", "text": "Try it on public services"},
                    {"id": "b", "text": "Publish it in the assessment"},
                    {"id": "c", "text": "Treat it as sensitive, rotate/remove it, and add a prevention check"},
                    {"id": "d", "text": "Put it into the device name"},
                ],
                "answer": "c",
                "explanation": "The value should not be used or disclosed; remediate the source and add a build-time prevention control.",
            },
            {
                "id": "q4",
                "question": "Who should review hazardous physical hardware changes?",
                "options": [
                    {"id": "a", "text": "Any person who can edit the firmware"},
                    {"id": "b", "text": "A qualified professional familiar with the device and its limits"},
                    {"id": "c", "text": "An online poll"},
                    {"id": "d", "text": "The course quiz"},
                ],
                "answer": "b",
                "explanation": "Physical and electrical work requires relevant qualified review and manufacturer documentation.",
            },
        ],
        "resources": [
            {"title": "RevelaAI Field Kit checklist", "url": "https://github.com/musombi123/RevelaAI/blob/main/docs/HARDWARE_LAB_CHECKLIST.md"},
            {"title": "NIST Technical Guide to Information Security Testing and Assessment", "url": "https://csrc.nist.gov/pubs/sp/800/115/final"},
        ],
    },
    {
        "id": "vulnerability-research-and-remediation",
        "title": "Vulnerability Research and Patch Engineering",
        "subtitle": "Move from an evidence-backed weakness to a verified defensive fix.",
        "category": "Security Engineering",
        "level": "Advanced",
        "duration_minutes": 150,
        "description": "Practice root-cause analysis, safe reproduction, severity communication, patch design, and regression testing using controlled examples and your own code.",
        "outcomes": [
            "Classify a weakness using an established taxonomy.",
            "Write a minimal, safe, reproducible finding.",
            "Prioritize risk using context and evidence.",
            "Implement a root-cause fix and verify it with regression tests.",
        ],
        "tags": ["CWE", "CVSS", "patching", "secure code review", "regression"],
        "lessons": [
            {
                "id": "weakness-taxonomy",
                "title": "Classify the weakness and its root cause",
                "duration_minutes": 35,
                "summary": "Describe what failed before deciding what to fix.",
                "sections": [
                    {
                        "heading": "Name the weakness precisely",
                        "body": "Use CWE to describe the underlying weakness class, not simply the visible symptom. For example, an authorization failure, an input-validation failure, and an insecure cryptographic design require different fixes. Map a finding to the closest supported weakness and explain why the mapping fits.",
                        "key_points": [
                            "Separate root cause from impact.",
                            "Use a recognized weakness identifier where appropriate.",
                            "Do not claim a vulnerability based on a tool alert alone.",
                        ],
                    },
                    {
                        "heading": "Build an evidence-led finding",
                        "body": "Record the affected asset and version, scope, preconditions, expected behavior, observed behavior, minimal safe reproduction, redacted evidence, impact, confidence, references, remediation, owner, and retest result. Clearly mark facts, inferences, and unknowns.",
                        "key_points": [
                            "Use synthetic data and a controlled test case.",
                            "Remove passwords, tokens, and personal data from evidence.",
                            "State when a result has not been independently validated.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Classify a flaw in your own code",
                    "environment": "A small code sample you wrote or an intentionally vulnerable local training example.",
                    "steps": [
                        "Choose a non-destructive weakness in your own test project.",
                        "Describe the root cause without including a weaponized payload.",
                        "Find an appropriate CWE entry and explain the mapping.",
                        "Write expected and observed behavior using synthetic inputs.",
                        "List what evidence is still missing before calling the issue confirmed.",
                    ],
                    "evidence": [
                        "A CWE mapping with rationale.",
                        "A draft finding with confidence and limitations.",
                    ],
                    "safety": "Do not test real accounts, production data, or systems outside your written scope.",
                },
            },
            {
                "id": "risk-and-remediation",
                "title": "Prioritize risk and design the correction",
                "duration_minutes": 40,
                "summary": "Evaluate impact in context and fix the underlying control.",
                "sections": [
                    {
                        "heading": "Risk is contextual",
                        "body": "CVSS communicates technical severity, but business risk also depends on asset value, exposure, prerequisites, affected users, compensating controls, and operational impact. Use the current CVSS version and record the assumptions behind each metric. Do not present a severity score as a prediction that exploitation will occur.",
                        "key_points": [
                            "State the deployment context and attack preconditions.",
                            "Explain the impact on confidentiality, integrity, and availability.",
                            "Record uncertainty and compensating controls.",
                        ],
                    },
                    {
                        "heading": "Fix the violated assumption",
                        "body": "A robust fix restores the intended security property. Examples include enforcing object ownership on the server, validating data at the trust boundary, removing secrets from the build, using platform cryptography, or constraining a parser. Prefer a small change that can be reviewed and tested over an opaque rewrite.",
                        "key_points": [
                            "Correct the root cause rather than hiding the interface.",
                            "Preserve existing API contracts where possible.",
                            "Add a test that would have failed before the fix.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Write a patch plan",
                    "environment": "Use the same local test project from the preceding lesson.",
                    "steps": [
                        "Choose the security property that the code should enforce.",
                        "Write the minimal change that restores that property.",
                        "Identify compatibility and migration risks.",
                        "Define unit, integration, and negative authorization tests.",
                        "Record the residual risk after the change.",
                    ],
                    "evidence": [
                        "A focused patch proposal.",
                        "A test matrix for expected and denied behavior.",
                    ],
                    "safety": "Keep the patch in a local feature branch until reviewed; do not auto-deploy generated changes.",
                },
            },
            {
                "id": "regression-and-report",
                "title": "Regression, review, and responsible disclosure",
                "duration_minutes": 35,
                "summary": "Verify the patch and communicate the result responsibly.",
                "sections": [
                    {
                        "heading": "Retest the security property",
                        "body": "Re-run the original safe test, add negative and boundary cases, and verify neighboring features. A passing unit test does not replace integration tests when identity, tenant boundaries, or external dependencies are involved. Keep the results attached to the exact commit or release candidate.",
                        "key_points": [
                            "Test allowed and denied cases.",
                            "Run the relevant existing test suite.",
                            "Record the build and commit used for retesting.",
                        ],
                    },
                    {
                        "heading": "Report responsibly",
                        "body": "Share a concise report with the responsible owner, provide reproducible evidence within scope, and allow a coordinated remediation process. Avoid public disclosure of secrets, exploit chains, user data, or unpatched details that would create unnecessary risk.",
                        "key_points": [
                            "Include scope, impact, remediation, and retest status.",
                            "Keep sensitive proof private and redacted.",
                            "Do not claim a fix is verified until the required tests have run.",
                        ],
                    },
                ],
                "lab": {
                    "title": "Close a finding with a retest record",
                    "environment": "A local feature branch and test suite for code you control.",
                    "steps": [
                        "Run the test that reproduces the original weakness in the controlled fixture.",
                        "Apply the proposed fix and rerun the same test.",
                        "Run neighboring regression tests and record the exact results.",
                        "Link the finding to the reviewed commit and test output.",
                        "Write a short closure statement separating verified facts from remaining limitations.",
                    ],
                    "evidence": [
                        "Before/after test results.",
                        "A concise final report with reviewer and retest status.",
                    ],
                    "safety": "No automatic merge or deployment is performed by this course. Human review remains mandatory.",
                },
            },
        ],
        "quiz": [
            {
                "id": "q1",
                "question": "What should a CWE mapping identify?",
                "options": [
                    {"id": "a", "text": "The underlying weakness class"},
                    {"id": "b", "text": "The author's name"},
                    {"id": "c", "text": "The severity score only"},
                    {"id": "d", "text": "The location of the hosting server"},
                ],
                "answer": "a",
                "explanation": "CWE describes common software and hardware weakness classes.",
            },
            {
                "id": "q2",
                "question": "Which statement about CVSS is most accurate?",
                "options": [
                    {"id": "a", "text": "It guarantees exploitation"},
                    {"id": "b", "text": "It communicates technical severity using defined metrics"},
                    {"id": "c", "text": "It replaces business-risk analysis"},
                    {"id": "d", "text": "It proves an alert is a vulnerability"},
                ],
                "answer": "b",
                "explanation": "CVSS provides a repeatable technical severity framework; deployment context and business risk still matter.",
            },
            {
                "id": "q3",
                "question": "What is the strongest remediation approach?",
                "options": [
                    {"id": "a", "text": "Hide the failing button"},
                    {"id": "b", "text": "Suppress the scanner output"},
                    {"id": "c", "text": "Correct the root cause and add regression tests"},
                    {"id": "d", "text": "Delete the audit record"},
                ],
                "answer": "c",
                "explanation": "A root-cause correction with regression coverage protects the intended security property.",
            },
            {
                "id": "q4",
                "question": "When can a finding be marked as verified fixed?",
                "options": [
                    {"id": "a", "text": "Immediately after writing a patch idea"},
                    {"id": "b", "text": "After the required retests pass for the reviewed version"},
                    {"id": "c", "text": "When the UI displays a green icon"},
                    {"id": "d", "text": "When no one reports the issue for one day"},
                ],
                "answer": "b",
                "explanation": "A fix is verified only after relevant tests have run against the exact version being assessed.",
            },
        ],
        "resources": [
            {"title": "MITRE Common Weakness Enumeration", "url": "https://cwe.mitre.org/"},
            {"title": "FIRST CVSS v4.0", "url": "https://www.first.org/cvss/v4-0/"},
            {"title": "OWASP Application Security Verification Standard", "url": "https://owasp.org/www-project-application-security-verification-standard/"},
        ],
    },
]

COURSE_GUARDRAILS = {
    "profile": "defensive_reverse_engineering",
    "scope": "assets owned by the learner or explicitly authorized in writing",
    "lab_mode": "local_or_isolated_training_only",
    "binary_execution_by_api": False,
    "remote_scanning_by_api": False,
    "automatic_target_modification": False,
    "automatic_merge_or_deployment": False,
    "human_review_required_for_consequential_changes": True,
    "restricted_activity": [
        "credential theft or use of discovered credentials",
        "unauthorized access or privilege escalation",
        "malware deployment, persistence, or evasion",
        "covert surveillance or non-consensual tracking",
        "safety-control bypass or unauthorized firmware flashing",
        "destructive testing outside an explicitly approved lab",
    ],
}
