const path = require('path');
const webpack = require('webpack');
const CopyPlugin = require('copy-webpack-plugin');

const extensionConfig = {
  target: 'node',
  mode: 'none',
  entry: './src/extension.ts',
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'extension.js',
    libraryTarget: 'commonjs2'
  },
  externals: {
    vscode: 'commonjs vscode',
    bufferutil: 'commonjs bufferutil',
    'utf-8-validate': 'commonjs utf-8-validate',
  },
  resolve: {
    extensions: ['.ts', '.js'],
    mainFields: ['module', 'main'],
    alias: {
      '@sovara/shared-components': path.resolve(__dirname, '../shared_components')
    },
    modules: [path.resolve(__dirname, 'node_modules'), 'node_modules']
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: [
          {
            loader: 'ts-loader',
            options: {
              transpileOnly: true
            }
          }
        ]
      }
    ]
  },
  devtool: 'nosources-source-map',
  infrastructureLogging: {
    level: "log",
  },
};

const webviewConfig = {
  target: 'web',
  mode: 'development',
  entry: './src/webview/index.tsx',
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'webview.js'
  },
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx'],
    mainFields: ['browser', 'module', 'main'],
    alias: {
      '@sovara/shared-components': path.resolve(__dirname, '../shared_components')
    },
    modules: [path.resolve(__dirname, 'node_modules'), 'node_modules'],
    fallback: {
      "path": false,
      "fs": false
    }
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        exclude: /node_modules/,
        use: [
          {
            loader: 'ts-loader',
            options: {
              transpileOnly: true
            }
          }
        ]
      },
      {
        test: /\.css$/,
        use: [
          'style-loader',
          {
            loader: 'css-loader',
            options: {
              importLoaders: 1
            }
          }
        ]
      },
      {
        test: /\.(png|jpe?g|gif|svg)$/i,
        type: 'asset/resource',
      }
    ]
  },
  plugins: [
    new webpack.DefinePlugin({
      'process.env': JSON.stringify({}),
      'process.platform': JSON.stringify(process.platform),
      'process.version': JSON.stringify(process.version),
      'process.versions': JSON.stringify(process.versions),
      'process.type': JSON.stringify(process.type),
      'process.arch': JSON.stringify(process.arch),
      'process.env.NODE_ENV': JSON.stringify('production')
    }),
    new CopyPlugin({
      patterns: [
        { from: path.resolve(__dirname, 'node_modules/@vscode/codicons/dist/codicon.css'), to: 'codicons/' },
        { from: path.resolve(__dirname, 'node_modules/@vscode/codicons/dist/codicon.ttf'), to: 'codicons/' },
        { from: 'icon.png', to: 'icon.png' }
      ]
    })
  ],
  devtool: 'source-map'
};

module.exports = [extensionConfig, webviewConfig];
