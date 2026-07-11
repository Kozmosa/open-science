import promqlGrammar from "./promql.tmLanguage.json" with { type: "json" };

export default {
  ...promqlGrammar,
  name: "promql",
  aliases: ["PromQL", "prometheus"],
};
