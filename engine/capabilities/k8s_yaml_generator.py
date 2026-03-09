"""
K8s YAML 生成能力

生成 Kubernetes 资源配置文件。
"""
from typing import Dict, Any, Type, Optional, List
from pydantic import BaseModel, Field
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult


class K8sDeploymentInput(BaseModel):
    """
    K8s Deployment 生成输入

    Attributes:
        app_name: 应用名称
        image: 容器镜像
        replicas: 副本数
        port: 容器端口
        cpu_request: CPU 请求
        memory_request: 内存请求
        cpu_limit: CPU 限制
        memory_limit: 内存限制
        env_vars: 环境变量
        labels: 标签
    """
    app_name: str = Field(..., description="应用名称", min_length=1, max_length=64)
    image: str = Field(..., description="容器镜像", min_length=1)
    replicas: int = Field(default=1, description="副本数", ge=1, le=100)
    port: int = Field(default=80, description="容器端口", ge=1, le=65535)
    cpu_request: str = Field(default="100m", description="CPU 请求")
    memory_request: str = Field(default="128Mi", description="内存请求")
    cpu_limit: str = Field(default="500m", description="CPU 限制")
    memory_limit: str = Field(default="512Mi", description="内存限制")
    env_vars: Optional[Dict[str, str]] = Field(default=None, description="环境变量")
    labels: Optional[Dict[str, str]] = Field(default=None, description="标签")


class K8sServiceInput(BaseModel):
    """
    K8s Service 生成输入

    Attributes:
        app_name: 应用名称
        port: 服务端口
        target_port: 目标端口
        service_type: 服务类型
    """
    app_name: str = Field(..., description="应用名称", min_length=1, max_length=64)
    port: int = Field(default=80, description="服务端口", ge=1, le=65535)
    target_port: int = Field(default=80, description="目标端口", ge=1, le=65535)
    service_type: str = Field(default="ClusterIP", description="服务类型",
                              pattern="^(ClusterIP|NodePort|LoadBalancer)$")


class K8sYamlGenerator(BaseCapability):
    """
    K8s YAML 生成器

    生成 Kubernetes Deployment 和 Service 配置文件。

    使用示例:
        >>> generator = K8sYamlGenerator()
        >>> result = await generator.dispatch(
        ...     app_name="my-app",
        ...     image="nginx:latest",
        ...     replicas=3,
        ...     port=8080
        ... )
    """

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="generate_k8s_yaml",
            description="生成 Kubernetes Deployment 和 Service YAML 配置",
            version="1.0.0",
            tags=["kubernetes", "k8s", "yaml", "deployment"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return K8sDeploymentInput

    @with_timeout(timeout_seconds=15)
    @with_error_handling("K8S_YAML_GENERATION_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        生成 K8s YAML

        Args:
            app_name: 应用名称
            image: 容器镜像
            replicas: 副本数
            port: 容器端口
            cpu_request: CPU 请求
            memory_request: 内存请求
            cpu_limit: CPU 限制
            memory_limit: 内存限制
            env_vars: 环境变量
            labels: 标签

        Returns:
            ActionResult: 生成的 YAML
        """
        try:
            input_data = K8sDeploymentInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        # 生成 Deployment
        deployment_yaml = self._generate_deployment(input_data)

        # 生成 Service
        service_input = K8sServiceInput(
            app_name=input_data.app_name,
            port=input_data.port,
            target_port=input_data.port,
            service_type="ClusterIP"
        )
        service_yaml = self._generate_service(service_input)

        return ActionResult.ok({
            "deployment": deployment_yaml,
            "service": service_yaml,
            "combined": f"{deployment_yaml}\n---\n{service_yaml}"
        })

    def _generate_deployment(self, input_data: K8sDeploymentInput) -> str:
        """
        生成 Deployment YAML

        Args:
            input_data: 输入参数

        Returns:
            Deployment YAML 字符串
        """
        labels = input_data.labels or {"app": input_data.app_name}
        label_yaml = "\n".join([f"    {k}: {v}" for k, v in labels.items()])

        env_yaml = ""
        if input_data.env_vars:
            env_lines = []
            for k, v in input_data.env_vars.items():
                env_lines.append(f"""        - name: {k}
          value: "{v}" """)
            env_yaml = "\n        env:\n" + "\n".join(env_lines)

        return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {input_data.app_name}
  labels:
{label_yaml}
spec:
  replicas: {input_data.replicas}
  selector:
    matchLabels:
      app: {input_data.app_name}
  template:
    metadata:
      labels:
        app: {input_data.app_name}
    spec:
      containers:
      - name: {input_data.app_name}
        image: {input_data.image}
        ports:
        - containerPort: {input_data.port}
        resources:
          requests:
            cpu: {input_data.cpu_request}
            memory: {input_data.memory_request}
          limits:
            cpu: {input_data.cpu_limit}
            memory: {input_data.memory_limit}{env_yaml}"""

    def _generate_service(self, input_data: K8sServiceInput) -> str:
        """
        生成 Service YAML

        Args:
            input_data: 输入参数

        Returns:
            Service YAML 字符串
        """
        return f"""apiVersion: v1
kind: Service
metadata:
  name: {input_data.app_name}
  labels:
    app: {input_data.app_name}
spec:
  type: {input_data.service_type}
  selector:
    app: {input_data.app_name}
  ports:
  - port: {input_data.port}
    targetPort: {input_data.target_port}
    protocol: TCP"""


class K8sConfigMapGenerator(BaseCapability):
    """
    K8s ConfigMap 生成器

    生成 Kubernetes ConfigMap 配置文件。
    """

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="generate_k8s_configmap",
            description="生成 Kubernetes ConfigMap YAML 配置",
            version="1.0.0",
            tags=["kubernetes", "k8s", "yaml", "configmap"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        # 复用 Deployment 输入的 subset
        return K8sDeploymentInput

    @with_timeout(timeout_seconds=10)
    @with_error_handling("K8S_CONFIGMAP_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        生成 ConfigMap YAML

        Args:
            app_name: 配置名称
            env_vars: 配置数据

        Returns:
            ActionResult: 生成的 YAML
        """
        app_name = kwargs.get("app_name", "config")
        env_vars = kwargs.get("env_vars", {})

        if not env_vars:
            # 如果传入了 K8sDeploymentInput，提取 env_vars
            try:
                input_data = K8sDeploymentInput(**kwargs)
                app_name = input_data.app_name
                env_vars = input_data.env_vars or {}
            except ValueError:
                pass

        yaml_content = self._generate_configmap(app_name, env_vars)
        return ActionResult.ok({"configmap": yaml_content})

    def _generate_configmap(self, name: str, data: Dict[str, str]) -> str:
        """生成 ConfigMap YAML"""
        data_yaml = "\n".join([f"  {k}: \"{v}\"" for k, v in data.items()])

        return f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: {name}
  labels:
    app: {name}
data:
{data_yaml}"""


class K8sIngressGenerator(BaseCapability):
    """
    K8s Ingress 生成器

    生成 Kubernetes Ingress 配置文件。
    """

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="generate_k8s_ingress",
            description="生成 Kubernetes Ingress YAML 配置",
            version="1.0.0",
            tags=["kubernetes", "k8s", "yaml", "ingress"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return BaseModel  # 使用通用模式

    @with_timeout(timeout_seconds=10)
    @with_error_handling("K8S_INGRESS_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """
        生成 Ingress YAML

        Args:
            name: Ingress 名称
            host: 域名
            service_name: 后端服务名称
            service_port: 后端服务端口
            path: 路径
            ingress_class: Ingress 类型
            tls_secret: TLS 密钥名称（可选）

        Returns:
            ActionResult: 生成的 YAML
        """
        name = kwargs.get("name", "ingress")
        host = kwargs.get("host", "example.com")
        service_name = kwargs.get("service_name", "app")
        service_port = kwargs.get("service_port", 80)
        path = kwargs.get("path", "/")
        ingress_class = kwargs.get("ingress_class", "nginx")
        tls_secret = kwargs.get("tls_secret")

        yaml_content = self._generate_ingress(
            name, host, service_name, service_port, path, ingress_class, tls_secret
        )
        return ActionResult.ok({"ingress": yaml_content})

    def _generate_ingress(
        self,
        name: str,
        host: str,
        service_name: str,
        service_port: int,
        path: str,
        ingress_class: str,
        tls_secret: Optional[str] = None
    ) -> str:
        """生成 Ingress YAML"""
        tls_section = ""
        if tls_secret:
            tls_section = f"""  tls:
  - hosts:
    - {host}
    secretName: {tls_secret}
"""

        return f"""apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {name}
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: {ingress_class}
{tls_section}  rules:
  - host: {host}
    http:
      paths:
      - path: {path}
        pathType: Prefix
        backend:
          service:
            name: {service_name}
            port:
              number: {service_port}"""
