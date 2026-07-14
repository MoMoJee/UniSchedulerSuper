import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src/", import.meta.url));
const prohibited = [
  "/get_calendar/events/",
  "/get_calendar/update_events/",
  "/events/create_event/",
  "/api/events/bulk-edit/",
  "/api/todos/",
  "/api/reminders/",
  "PlannerManager",
];

async function visit(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(
    entries.map(async (entry) => {
      const path = join(directory, entry.name);
      return entry.isDirectory() ? visit(path) : [path];
    }),
  );
  return files.flat();
}

const failures = [];
for (const file of await visit(root)) {
  if (!/\.(?:ts|tsx)$/.test(file)) continue;
  const source = await readFile(file, "utf8");
  for (const token of prohibited) {
    if (source.includes(token))
      failures.push(`${file}: prohibited legacy Planner reference ${token}`);
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log(
    "No legacy Planner URLs or manager references found in frontend/src.",
  );
}
