# Task graph review

Task discovery deterministically selects up to 12 eligible Calc/Writer/Chrome/file
tasks with seed recorded in the manifest. The strong API creates drafts only. Reviewers
inspect the instruction, nodes, dependencies, expected results, and evidence modes,
then approve, edit, or reject. A runnable graph must contain `approved: true`, reviewer,
and timestamp; the experiment runner rejects every unapproved graph.
