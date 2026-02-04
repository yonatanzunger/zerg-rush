# Zerg Rush Development Guidelines

Whenever making architectural changes, design decisions, or implementing new features, please refer to the following documentation to ensure alignment with the project's goals and standards.

See `.clarity-protocol/metadata.json` for basic metadata about this project.
See `.clarity-protocol/problem.md` for detailed information about the problem this project is intended to solve. This should guide your overall approach to design and implementation.
See `.clarity-protocol/solution/user-perspective.md` for detailed information about the intended user experience and user interface design. This should guide your frontend design and implementation decisions.
See `.clarity-protocol/solution/architecture.md` for detailed information about the intended solution architecture from a technical perspective. This should guide your design and implementation decisions.

## Agent notes

- Explore the project before beginning code generation
- Create todo lists for long operations
  - Before each step in a todo list, reread the instructions to ensure you always have the right directions
- Always use instructions files when available, reviewing before generating code
- Do not generate summary markdown files upon completion of a task
- Always use absolute paths when running scripts and BASH commands
- **Do NOT commit or push changes unless explicitly instructed to do so by the user**

## Code standards

### Required Before Each Commit

#### Testing guidelines

- Run Python tests to ensure backend functionality, and Playwright tests to ensure e2e and frontend functionality
- Review the existing tests to ensure we're not duplicating efforts
- Test code should be of the same quality as the rest of the project, and follow DRY principles
- Python tests should run using `pytest` framework and use the `unittest` library and its built-in assertions for structuring tests
- For frontend changes, run builds in the client directory to verify build success and the end-to-end tests, to ensure everything works correctly
- When making API changes, update and run the corresponding tests to ensure everything works correctly

#### Project guidelines

- When updating models, ensure database migrations are included if needed
- When adding new functionality, make sure you update the README
- Make sure all guidance in the Copilot Instructions file is updated with any relevant changes, including to project structure and scripts, and programming guidance
- Update any relevant files in .clarity-protocol to ensure they reflect the current state of the project

### Code formatting requirements

- When writing Python, you must use type hints for return values, and function parameters, and any variables with non-obvious types.
- Follow PEP 8 style guidelines for Python code and use `black` for formatting.

### Python and Flask Patterns

- Use Flask blueprints for organizing routes
- Follow RESTful API design principles

### Svelte and Astro Patterns

- **Svelte 5 Components**: Use runes-based reactivity (`$state`, `$derived`, `$effect`, `$props`) - see `svelte.instructions.md`
- **Astro Pages**: Use Astro for routing, layouts, and static content - see `astro.instructions.md`
- Create reusable Svelte components when functionality is used in multiple places
- Use `client:only="svelte"` directive when embedding Svelte in Astro pages

### Styling

- Use Tailwind CSS utility classes exclusively - see `tailwindcss.instructions.md`
- Dark theme colors: slate palette (`bg-slate-800`, `text-slate-100`, etc.)
- Rounded corners and modern UI patterns
- Follow modern UI/UX principles with clean, accessible interfaces

### GitHub Actions workflows

- Follow good security practices
- Make sure to explicitly set the workflow permissions
- Add comments to document what tasks are being performed

## Scripts

- Several scripts exist in the `scripts` folder
- Always use available scripts to perform tasks rather than performing operations manually
- Existing scripts (use `.sh` on Linux/macOS/Codespaces, `.ps1` on Windows):
  - `scripts/setup-env`: Performs installation of all Python and Node dependencies
  - `scripts/run-server-tests`: Calls setup-env, then runs all Python tests
  - `scripts/run-e2e-tests`: Runs Playwright E2E tests for frontend
  - `scripts/start-app`: Calls setup-env, then starts both backend and frontend servers

## Repository Structure

TBD
