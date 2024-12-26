from config import Config

def debug_config():
    config = Config()
    
    print("Loading configuration files...")
    
    print("\nDefault config (config.yaml):")
    print(config._load_yaml("config.yaml"))
    
    print("\nLocal config (config.local.yaml):")
    print(config._load_yaml("config.local.yaml"))
    
    print("\nMerged config:")
    print(config.config)
    
    print("\nWallet values:")
    print(f"Target wallet: {config.get('secrets', 'target_wallet')}")
    print(f"Follower seed: {config.get('secrets', 'follower_seed')}")

if __name__ == "__main__":
    debug_config()