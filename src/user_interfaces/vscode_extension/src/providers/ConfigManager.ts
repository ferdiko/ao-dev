import * as fs from 'fs';
import * as yaml from 'js-yaml';

export interface Config {
  // Fields will be added as needed (e.g., playbook settings)
}

type ConfigChangeCallback = (config: Config) => void;

export class ConfigManager {
  private static instance: ConfigManager;
  private configPath?: string;
  private watcher?: fs.StatWatcher;
  private listeners: ConfigChangeCallback[] = [];
  private currentConfig?: Config;

  private constructor() {}

  public static getInstance(): ConfigManager {
    if (!ConfigManager.instance) {
      ConfigManager.instance = new ConfigManager();
    }
    return ConfigManager.instance;
  }

  public setConfigPath(path: string): void {
    if (this.configPath === path) {
      return; // Already set to same path
    }

    // Clean up existing watcher
    this.dispose();
    
    this.configPath = path;
    this.setupWatcher();
    
    // Load initial config and notify listeners
    const config = this.loadConfig();
    this.currentConfig = config;
    this.notifyListeners(config);
  }

  public getCurrentConfig(): Config | undefined {
    return this.currentConfig;
  }

  public onConfigChange(callback: ConfigChangeCallback): void {
    this.listeners.push(callback);
    
    // If we already have a config, notify immediately
    if (this.currentConfig) {
      callback(this.currentConfig);
    }
  }

  private setupWatcher(): void {
    if (!this.configPath) {
      return;
    }

    try {
      this.watcher = fs.watchFile(this.configPath, (current, previous) => {
        if (current.mtime !== previous.mtime) {
          console.log('Config file changed, reloading...');
          const config = this.loadConfig();
          this.currentConfig = config;
          this.notifyListeners(config);
        }
      });
    } catch (error) {
      console.warn('Failed to set up config watcher:', error);
    }
  }

  private loadConfig(): Config {
    if (!this.configPath) {
      return {};
    }

    try {
      if (fs.existsSync(this.configPath)) {
        yaml.load(fs.readFileSync(this.configPath, 'utf8')) as any;
        return {};
      } else {
        console.warn(`Config file not found at: ${this.configPath} — using defaults`);
      }
    } catch (error) {
      console.warn('Failed to read config from path:', this.configPath, error);
    }

    return {};
  }

  private notifyListeners(config: Config): void {
    this.listeners.forEach(callback => {
      try {
        callback(config);
      } catch (error) {
        console.error('Error in config change callback:', error);
      }
    });
  }

  public dispose(): void {
    if (this.watcher && this.configPath) {
      fs.unwatchFile(this.configPath);
      this.watcher = undefined;
    }
    this.listeners = [];
    this.currentConfig = undefined;
    this.configPath = undefined;
  }
}

// Export singleton instance
export const configManager = ConfigManager.getInstance();