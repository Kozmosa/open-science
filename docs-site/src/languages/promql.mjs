import promqlGrammar from './promql.tmLanguage.json' with { type: 'json' };

const promqlLanguage = {
  ...promqlGrammar,
  name: 'promql',
  aliases: ['PromQL', 'prometheus'],
};

export default promqlLanguage;
