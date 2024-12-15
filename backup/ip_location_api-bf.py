# encoding:utf-8

import requests

# 定义一个函数来调用IP地理位置定位API
def call_ip_location_api(ip_address):
    # API的基本URL
    base_url = "https://app.ipdatacloud.com/v2/free_query" 
    
    # 完整的请求URL，包含需要查询的IP地址
    request_url = f"{base_url}?ip={ip_address}"
    
    # 发送GET请求
    response = requests.get(request_url)
    
    # 检查响应状态码
    if response.status_code == 200:
        # 解析JSON数据
        data = response.json()
        # 打印返回的数据
        print("IP地理位置定位结果：")
        print(f"城市: {data['data']['city']}")
        print(f"国家: {data['data']['country']}")
        print(f"国家英文名称: {data['data']['country_english']}")
        print(f"IP地址: {data['data']['ip']}")
        print(f"互联网服务提供商: {data['data']['isp']}")
        print(f"省份: {data['data']['province']}")
    else:
        # 如果响应码不是200，打印错误信息
        print(f"请求失败，状态码：{response.status_code}")

# 主函数，用于执行脚本
def main():
    # 这里使用一个示例IP地址，您可以替换为任何有效的IP地址
    ip_address = "8.8.8.8"
    call_ip_location_api(ip_address)

if __name__ == "__main__":
    main()
