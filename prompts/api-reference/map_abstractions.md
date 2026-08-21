<!-- NOTE: This template is NOT used in the current api-reference flow.
     ContextRouter routes api-reference mode to DeterministicFileMapper,
     which bypasses abstraction discovery entirely (1:1 file mapping).
     Kept for potential future use if api-reference adds a non-deterministic path. -->

For the project `{project_name}`:

Codebase Context (Batch):
{context}

Full Project Directory Structure:
{directory_tree}

{language_instruction}Analyze this batch of the codebase. Your task is to identify ALL logical API modules, classes, and internal functions in this batch for an exhaustive API reference.
Do not use beginner analogies. Focus strictly on grouping by technical interfaces and architecture.

You MUST preserve core logic, architectural patterns, class structures, and function signatures with minimal loss.
You MUST identify at least 3 modules per batch, even if files seem closely related.
Distinguish between: service/logic files vs. data model/schema files vs. configuration/infrastructure files.

This batch is one slice of a larger codebase. The full directory structure is provided above for context.
If you see references to external types, namespaces, or services not present in this batch,
mention them as "external dependencies" in the description but do NOT create modules for code you cannot see.

For each API module, provide:
1. A concise `name` for the module{name_lang_hint}.
2. A technical `description` of 100-250 words detailing its role and public API surface{desc_lang_hint}.
   Include: (a) its functional responsibility in the system,
   (b) key classes/interfaces and their purpose,
   (c) its dependencies on other components (including external ones from other batches).
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    QueryOptimizer{name_lang_hint}
  description: |
    Optimizes AST trees before execution. Implements cost-based optimization with the CostEstimator class and rule-based rewrites via the OptimizationRule interface. Depends on the external Parser module (not in this batch) for AST input.{desc_lang_hint}
  file_indices:
    - 5 # src/query/optimizer.py
    - 6 # src/query/cost_estimator.py
# ... as many as found in this batch
```