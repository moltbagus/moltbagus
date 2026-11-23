module.exports = {
  apps: [
    {
      name: 'tcg-bot',
      script: 'bot_async.py',
      cwd: __dirname,
      interpreter: 'python3',
      interpreter_args: '-u',
      env: {
        PYTHONUNBUFFERED: '1',
      },
      out_file: './bot-pm2.out.log',
      error_file: './bot-pm2.err.log',
      merge_logs: true,
    },
  ],
};
