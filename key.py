"""Simple container class for a keypair which is locally available"""
import pulumi_aws as aws


class Key:
    """Describes a keypair which is locally available"""

    def __init__(
        self, resource_name: str, public_key_path: str, private_key_path: str
    ) -> None:
        """Describes a key pair which we have access to the public and private
        key for. This creates they corresponding KeyPair on AWS so that we
        can initialize ec2 instances that are reachable via the given key.

        Args:
            resource_name (str): The name to use prefixing resources created by
                this instance
            public_key_path (str): The path to the file containing the public key
            private_key_path (str): The path to the file containing the private key
                in openssh format
        """
        self.resource_name: str = resource_name
        """The name to use to prefix resource names for resources created by this instance"""

        self.public_key_path: str = public_key_path
        """The path to the public key file"""

        self.private_key_path: str = private_key_path
        """The path to the private key file in openssh format"""

        with open(public_key_path) as f:
            public_key = f.read()

        self.key_pair: aws.ec2.KeyPair = aws.ec2.KeyPair(
            f"{resource_name}-kp",
            public_key=public_key,
            tags={"Name": f"from pulumi {resource_name}"},
        )
        """The key pair on aws referencing this key"""
