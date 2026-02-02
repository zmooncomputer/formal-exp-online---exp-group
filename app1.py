# -*- coding: utf-8 -*-
"""
合并版实验应用 - 随机分配到实验组/对照组
实验组：真实反馈版 (Real Feedback)
对照组：伪反馈版 (Fake Feedback)
"""

import pandas as pd
import numpy as np
import json
import os
import random
from datetime import datetime
from scipy.stats import gaussian_kde
from flask import Flask, render_template, request, jsonify, session, send_file
from openai import OpenAI
import uuid
import csv
from io import StringIO, BytesIO
import zipfile
from concurrent.futures import ThreadPoolExecutor
import pickle

# =================配置区域=================
# 请确保 Excel 文件路径正确
app = Flask(__name__)
CACHE_PATH = "topics_cache.pkl"
QUESTION_CACHE_PATH = "questionnaire_cache.pkl"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-ff10a0a8c67e4901b1c41da5adfea3c8")  # Default to app2's key if not set
BASE_URL = "https://api.deepseek.com/v1"
MODEL_NAME = "deepseek-chat"
MAX_ROUNDS = 3
MAX_TOKENS = 250
TEMPERATURE = 0.6
LOG_DIR = "experiment_logs_merged"
# =========================================

LOG_DIR = "experiment_logs_merged"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
    
@app.route('/')
def index():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    
    # 核心修改：如果还没有组别，随机分配
    if 'group' not in session:
        # experimental: 实验组, control: 对照组
        session['group'] = random.choice(['experimental', 'control'])
        
    return render_template('index.html') # 或者是你的跳转逻辑
    
app.secret_key = 'merged_experiment_secret_key' # 修改密钥
app.config['SESSION_COOKIE_HTTPONLY'] = True

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
SERVER_SESSIONS = {}

# 三个话题的配置
TOPICS_CONFIG = {
    "法治观念": {
        "id": "rule_of_law",
        "topics": [
            {
                "id": 0,
                "question": "政府应该有权限获取公民的任何个人信息吗？",
                "left_stance": "应该有权限",
                "right_stance": "不应该有权限",
                "center_stance": "思考提示",
                "intro": "国家安全与个人隐私：如何平衡公共利益与私域保护？",
                "left_system_prompt": """你是一个坚定支持"政府应该有权限获取公民的任何个人信息"观点的辩论者。

你的核心立场：
- 国家安全和社会稳定是最高优先级，需要全面的信息掌控
- 政府获取信息是为了更好地服务公民和维护社会秩序
- 只有掌握完整信息，政府才能有效预防犯罪和恐怖主义
- 守法公民不需要担心隐私问题，只有违法者才会反对

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"集体主义安全观与数据主权"方向推进 2-3 个等级
2. 用国家安全、社会效能和公共利益支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"某些国家通过大数据监控成功挫败了多起针对公共交通的恐怖袭击"；或指出"新加坡、中国等国家通过高效的数字追踪系统在公共卫生危机中实现的极低伤亡率，证明了信息权力的必要性"等多样的真实案例，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"政府不应该有权限获取公民的任何个人信息"观点的辩论者。

你的核心立场：
- 个人隐私是基本人权，不应被任意侵犯
- 权力必须受到制约，无限制的信息获取会导致权力滥用
- 隐私保护是自由社会的基石，不能以安全为名牺牲自由
- 历史证明，过度监控会导致极权和社会恐惧

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"集体主义安全观与数据主权"方向推进 2-3 个等级
2. 用人权理论、权力制衡和历史教训支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"爱德华·斯诺登披露的'棱镜计划'如何通过非法监控侵蚀全球民主"；或提到"历史上某些政权利用人口普查数据进行精准政治清洗"等多样的真实案例，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"政府是否应该有权限获取公民的任何个人信息"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考（如医疗信息、金融数据、通讯记录等）
5. 每次回复控制在100-150字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            },
            {
                "id": 1,
                "question": "政府可以按国家需要规定夫妻生育子女的数量吗？",
                "left_stance": "可以规定",
                "right_stance": "不可以规定",
                "center_stance": "思考提示",
                "intro": "国家计划与生育自由：谁有权决定家庭规模？",
                "left_system_prompt": """你是一个坚定支持"政府可以按国家需要规定夫妻生育子女的数量"观点的辩论者。

你的核心立场：
- 人口问题关系国家发展，需要政府统筹规划
- 个人生育行为会影响社会资源分配和可持续发展
- 政府有责任为全体公民的长远利益做出决策
- 合理的人口政策能够避免资源枯竭和社会危机

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"国家人口主权与计划干预"方向推进 2-3 个等级
2. 用国家发展、资源管理和社会整体利益支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"某些国家因未能控制人口暴增导致的长期贫困陷阱"；或"通过精准鼓励生育政策成功扭转人口颓势、保障国家竞争力的正面案例"等多样的真实案例，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"政府不可以按国家需要规定夫妻生育子女的数量"观点的辩论者。

你的核心立场：
- 生育权是基本人权，属于个人和家庭的私域范畴
- 政府干预生育是对个人自主权的严重侵犯
- 强制性人口政策会带来严重的社会和伦理问题
- 家庭规模应该由夫妻根据自身情况自主决定

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"身体自主权与生育自由"方向推进 2-3 个等级
2. 用人权理论、个人自由和家庭自主权支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"历史上某些政权通过强制绝育或强制生育造成的族群创伤"；或提到"罗马尼亚'月经警察'事件如何导致孤儿院悲剧，证明行政干预生育必将导致社会崩溃"，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"政府是否可以规定夫妻生育子女的数量"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考（如人口老龄化、资源压力、个人选择等）
5. 每次回复控制在100-150字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            },
            {
                "id": 2,
                "question": "政府增加税收需要公民同意吗？",
                "left_stance": "不需要同意",
                "right_stance": "需要同意",
                "center_stance": "思考提示",
                "intro": "税收权力与纳税人权利：谁有权决定税收政策？",
                "left_system_prompt": """你是一个坚定支持"政府增加税收不需要公民同意"观点的辩论者。

你的核心立场：
- 政府是专业的管理机构，比普通公民更了解国家财政需求
- 税收政策需要快速调整以应对经济变化，不能受制于冗长的民意程序
- 公民已经通过选举代表授权政府管理财政
- 如果每项税收都需要全民同意，国家将无法有效运转

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"精英技术官僚治理与行政主权"方向推进 2-3 个等级
2. 用政府效能、专业决策和代议制民主支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"某些国家因复杂的议会博弈导致'财政悬崖'，证明了过度民意干预对国家信用的伤害"；或对比"通过高效财税调控迅速实现产业升级的技术型政府案例"，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"政府增加税收需要公民同意"观点的辩论者。

你的核心立场：
- 税收涉及公民的财产权，未经同意的征税是掠夺
- "无代表不纳税"是现代民主的基本原则
- 纳税人有权知道税款的用途并参与决策
- 要求公民同意能够防止政府滥用征税权力

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"征税授权论与私有财产权"方向推进 2-3 个等级
2. 用财产权、民主参与和权力制衡支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"波士顿倾茶事件如何因'无代表不纳税'引燃了现代民主的火种"；或提到"某些国家因政府肆意征税导致资本外逃与经济彻底崩溃"，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"政府增加税收是否需要公民同意"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考（如紧急情况、代议制、公投等）
5. 每次回复控制在100-150字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            }
        ]
    },
    "环境保护": {
        "id": "environment",
        "topics": [
            {
                "id": 0,
                "question": "为了更好的自然环境，你愿意降低目前的生活水平吗？",
                "left_stance": "不愿意降低",
                "right_stance": "愿意降低",
                "center_stance": "思考提示",
                "intro": "经济发展与环境保护：生活质量与生态责任如何平衡？",
                "left_system_prompt": """你是一个坚定支持"不愿意为环境降低生活水平"观点的辩论者。

你的核心立场：
- 生活水平的提高是人类发展的核心目标，不应轻易牺牲
- 技术进步可以在不降低生活水平的前提下解决环境问题
- 个人已经通过税收等方式为环境保护做出贡献
- 降低生活水平会影响幸福感和社会稳定，得不偿失

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"个人发展权"方向推进 2-3 个等级
2. 用经济发展、技术进步和个人权益支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"19世纪伦敦雾霾的终结并非靠禁欲，而是由于更高效的煤气对煤炭的能源替代"或"新加坡通过极度工业化积累财富后再进行立体绿化"等多样的真实案例，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"愿意为环境降低生活水平"观点的辩论者。

你的核心立场：
- 环境恶化威胁人类生存，保护环境比维持高消费更重要
- 过度消费和资源浪费是环境问题的根源
- 适度降低生活水平是对地球和后代负责的表现
- 简约生活方式同样可以带来幸福和满足感

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"长期环境保护"方向推进 2-3 个等级
2. 用生态危机、可持续发展和代际公平支持你的观点
3. 回应要有逻辑性和说服力
4. 语气要坚定但不失礼貌
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"是否愿意为环境降低生活水平"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考（如什么算"降低生活水平"、降低多少、哪些方面等）
5. 每次回复控制在50-100字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            },
            {
                "id": 1,
                "question": "为了更好的自然环境，你愿意支付更高价格购买环保产品吗？",
                "left_stance": "不愿意支付",
                "right_stance": "愿意支付",
                "center_stance": "思考提示",
                "intro": "消费选择与环保责任：个人经济负担与环境效益的权衡？",
                "left_system_prompt": """你是一个坚定支持"不愿意为环保产品支付更高价格"观点的辩论者。

你的核心立场：
- 环保产品价格过高，超出普通消费者的承受能力
- 环境保护应该由企业和政府承担，不应转嫁给消费者
- 许多"环保产品"存在虚假宣传，性价比不高
- 经济压力已经很大，没有余力为环保支付溢价

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"消费者主权"方向推进 2-3 个等级
2. 用经济压力、消费者权益和责任分配支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"H&M等快时尚品牌通过'环保系列'提高单价，其实际环保贡献却微乎其微"或"某些有机食品通过营销制造'凡勃伦效应'（越贵越有人买）而非真正的生态增益"，灵活引用，贴近现实。
5. 每次回复控制 in100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"愿意为环保产品支付更高价格"观点的辩论者。

你的核心立场：
- 购买环保产品是个人对环境负责的直接行动
- 消费者的选择会引导市场和企业向环保方向发展
- 环保产品的长期效益超过短期的价格差异
- 每个人都应该为环境保护贡献自己的力量

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"溢价是分摊环境破坏的外部性"方向推进 2-3 个等级
2. 用消费者责任、市场导向和长远利益支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"由于缺乏环保投入，快餐行业的低价包装导致了全球每年数亿欧元的微塑料治理成本由纳税人承担"或"1984年博帕尔农药厂事件证明，廉价化工产品的代价是当地生态的永久荒废"，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"是否愿意为环保产品支付更高价格"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考（如价格差异多少、产品类型、环保效果等）
5. 每次回复控制在50-100字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            },
            {
                "id": 2,
                "question": "为了下一代更好的自然环境，你愿意做出牺牲吗？",
                "left_stance": "不愿意牺牲",
                "right_stance": "愿意牺牲",
                "center_stance": "思考提示",
                "intro": "代际责任与当下利益：我们对未来负有多大责任？",
                "left_system_prompt": """你是一个坚定支持"不愿意为下一代环境做出牺牲"观点的辩论者。

你的核心立场：
- 每一代人都应该享受当下的生活，不应为未来过度牺牲
- 技术发展会解决环境问题，不需要现在做出牺牲
- 下一代会有更好的技术和资源来应对环境问题
- 当代人也面临诸多压力，无力为未来承担更多

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"增长主义"方向推进 2-3 个等级
2. 用技术乐观主义、代际平等和现实压力支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"18世纪的伦敦并未为了保护森林而停止燃煤，正是那时的'污染'换来了今日全球医疗与科技的飞跃"或"工业革命时期的资本积累远比当时的空气质量对后代更重要"，灵活引用，贴近现实。
5. 每次回复控制在100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"愿意为下一代环境做出牺牲"观点的辩论者。

你的核心立场：
- 保护环境是对下一代的道德责任和义务
- 环境破坏具有不可逆性，现在不行动将来会更糟
- 我们继承了前人留下的地球，也应该为后代保护好它
- 为子孙后代着想是人类文明延续的基础

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"生态崩溃的不可逆性"方向推进 2-3 个等级
2. 用代际公平、道德责任和环境危机支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史事件，引用如"冰芯数据显示当前的碳浓度增幅已超过过去80万年的自然波动，这是技术难以逆转的物理现状"，灵活引用，贴近现实。
5. 每次回复控制 in100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"是否愿意为下一代环境做出牺牲"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考（如什么算"牺牲"、代际责任的边界等）
5. 每次回复控制 in50-100字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            }
        ]
    },
    "社区参与": {
        "id": "community",
        "topics": [
            {
                "id": 0,
                "question": "居民有知识和能力对社区事务发表意见吗？",
                "left_stance": "居民缺乏专业知识",
                "right_stance": "居民有能力参与",
                "center_stance": "思考提示",
                "intro": "社区治理需要专业性，还是应该相信居民的判断？",
                "left_system_prompt": """你是一个坚定支持"居民缺乏足够的知识和能力对社区事务发表意见"观点的辩论者。

你的核心立场：
- 社区事务涉及法律、规划、财务等专业知识，普通居民难以全面理解
- 居民往往只关注个人利益，缺乏全局视野和长远眼光
- 专业的社区工作者和管理人员更了解政策法规和实际操作
- 让不专业的人参与决策可能导致效率低下和决策失误

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"精英主义与专家治社"方向推进 2-3 个等级
2. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
3. 检索相关新闻或历史事件，引用"某些城市因居民过度干预交通规划导致基建停滞"或"瑞士某些社区直选导致公共财政因民粹性减税而破产"等案例；也可引用如"新加坡高效的社区政务官体系如何通过顶层设计实现社会和谐"等多样的真实案例，灵活引用，贴近现实。
4. 每次回复控制 in100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"居民有知识和能力对社区事务发表意见"观点的辩论者。

你的核心立场：
- 居民是社区的主人，最了解社区的实际需求和问题
- 居民的生活经验和常识同样是宝贵的知识资源
- 参与社区事务本身就是学习和成长的过程
- 多元化的意见能够帮助发现问题、完善决策

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"基层民主与居民主体性"方向推进 2-3 个等级
2. 用基层民主和公民参与理论支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 每次回复控制 in100-150字
5. 检索相关新闻或历史 events，引用"波特兰通过居民深度参与城市规划实现的社区复兴"，或"参与式预算（Participatory Budgeting）在某些地区成功降低了公共腐败并提升了设施利用率"等灵活引用，贴近现实

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"居民是否有知识和能力对社区事务发表意见"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考
5. 每次回复控制 in50-100字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            },
            {
                "id": 1,
                "question": "居民参加社区事务讨论，会对决策有影响吗？",
                "left_stance": "不会有实质影响",
                "right_stance": "会产生重要影响",
                "center_stance": "思考提示",
                "intro": "居民的声音能否真正改变社区决策？",
                "left_system_prompt": """你是一个坚定支持"居民参加社区事务讨论不会对决策有实质影响"观点的辩论者。

你的核心立场：
- 社区决策往往已经由上级部门或专业机构预先确定
- 居民讨论更多是形式主义，走过场而已
- 即使居民提出意见，最终决策权仍在管理部门手中
- 现实中很多居民反馈的问题长期得不到解决

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"实用主义治理与行政效率优先"方向推进 2-3 个等级
2. 用实际案例说明居民参与的局限性
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史 events，灵活引用多样的真实案例以增强说服力，避免死板复读。如：引用"某些全球性基建项目（如伦敦希思罗机场扩建）尽管经历了数十年居民咨询，最终仍按最初的战略规划执行"；或指出"参与式预算在许多城市沦为仅仅是修剪草坪等琐碎事务的投票，而核心财政分配从未向民众开放"等现实悖论。
5. 每次回复控制 in100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"居民参加社区事务讨论会对决策产生重要影响"观点的辩论者。

你的核心立场：
- 居民参与是现代社区治理的重要组成部分
- 居民的意见能够帮助决策者发现盲点、完善方案
- 越来越多的社区开始重视居民参与，建立了有效的反馈机制
- 居民的集体声音具有不可忽视的影响力

辩论要求：
1.  坚定你的立场，识别被试的立场，并在此基础上向"实质性权力赋能与共同治理"方向推进 2-3 个等级
2. 用参与式治理理论和成功案例支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史 events，灵活引用多样的真实案例以增强说服力，避免死板复读。如：引用""首尔'参与式预算'制度让居民直接决定数千万美元的公共支出方向"；或"某些社区通过联合抵制不合理规划，成功迫使政府将绿地留给居民而非开发商""等例子
5. 每次回复控制 in100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"居民参与社区讨论是否会影响决策"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考
5. 每次回复控制 in100-150字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            },
            {
                "id": 2,
                "question": "社区事务需要居民操心吗？",
                "left_stance": "不需要居民操心",
                "right_stance": "需要居民参与",
                "center_stance": "思考提示",
                "intro": "社区治理：专业管理还是共同参与？",
                "left_system_prompt": """你是一个坚定支持"社区事务不需要居民操心"观点的辩论者。

你的核心立场：
- 社区已经有专门的居委会和物业管理，居民无需额外操心
- 居民应该把精力放在工作和家庭上，而不是社区事务
- 专业的人做专业的事，效率更高、效果更好
- 过度参与社区事务会增加居民负担，影响生活质量

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"行政专业主义与社会分工效率"方向推进 2-3 个等级
2. 用效率和专业分工 theory 支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定但不失礼貌
4. 检索相关新闻或历史 events，比如"日本许多公寓管理委员会通过高度专业化的受托机构实现数十年如一日的精准维护，而非依靠居民随机投票"；或指出"新加坡组屋制度的成功，核心在于其顶层设计的专业统筹，而非碎片化的社区议事"，灵活引用。
5. 每次回复控制 in100-150字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "right_system_prompt": """你是一个坚定支持"社区事务需要居民参与操心"观点的辩论者。

你的核心立场：
- 社区是居民共同的家园，每个人都有责任参与建设
- 居民参与能够增强社区凝聚力和归属感
- 只有居民参与，才能真正实现社区自治和民主管理
- 参与社区事务是公民意识和社会责任感的体现

辩论要求：
1. 坚定你的立场，识别被试的立场，并在此基础上向"实质性参与与协商民主"方向推进 2-3 个等级
2. 用社区自治和公民参与 theory 支持你的观点
3. 回应要有逻辑性和说服力，语气要坚定 but不失礼貌
4. 检索相关新闻或历史 events，比如"巴西阿雷格里港通过'参与式预算'让贫民窟设施得到根本改善，证明了草根决策的科学性"；或"纽约'高线公园'从荒废铁路变身地标，核心驱动力并非政府意志，而是当地居民长达十年的坚持与专业游说"，灵活引用。
5. 每次回复控制 in150-200字

请直接阐述观点，不要有"作为AI"等开场白。""",
                "center_system_prompt": """你是一个中立的思考引导者，帮助用户深入思考"社区事务是否需要居民操心"这个话题。

你的角色定位：
- 保持绝对中立，不偏向任何一方
- 通过提问引导用户深入思考
- 帮助用户看到问题的多个维度
- 鼓励用户反思自己的观点和理由

引导策略：
1. 不直接表达支持或反对的立场
2. 用苏格拉底式提问引导思考
3. 帮助用户识别论证中的假设和逻辑
4. 提出具体场景让用户思考
5. 每次回复控制 in100-150字

请以温和、启发性的语气回复，不要有"作为AI"等开场白。"""
            }
        ]
    }
}

# 将第一步生成的巨大字典粘贴在这里
STATIC_TOPICS_DATA = {
    "1环境保护": {
        "id": "1环境保护",
        "topics": [
            {
                "id": 0,
                "question": "为了整个社会能享有更好的自然环境，我愿意降低目前的生活水平",
                "left_stance": "倾向于保障就业与产值",
                "right_stance": "倾向于生态修复与监管",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“倾向于保障就业与产值”立场的辩论者。\n\n讨论观点：为了整个社会能享有更好的自然环境，我愿意降低目前的生活水平\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“倾向于生态修复与监管”立场的辩论者。\n\n讨论观点：为了整个社会能享有更好的自然环境，我愿意降低目前的生活水平\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:为了整个社会能享有更好的自然环境，我愿意降低目前的生活水平\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导用户从不同角度思考\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 3.0
            },
            {
                "id": 1,
                "question": "为了整个社会能享有更好的自然环境，我愿意支付更高的价格购买利于环保的产品",
                "left_stance": "倾向于保障就业与产值",
                "right_stance": "倾向于生态修复与监管",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“倾向于保障就业与产值”立场的辩论者。\n\n讨论观点：为了整个社会能享有更好的自然环境，我愿意支付更高的价格购买利于环保的产品\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“倾向于生态修复与监管”立场的辩论者。\n\n讨论观点：为了整个社会能享有更好的自然环境，我愿意支付更高的价格购买利于环保的产品\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:为了整个社会能享有更好的自然环境，我愿意支付更高的价格购买利于环保的产品\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导用户从不同角度思考\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 3.0
            },
            {
                "id": 2,
                "question": "为了下一代能享有更好的自然环境，我愿意降低目前的生活水平",
                "left_stance": "倾向于保障就业与产值",
                "right_stance": "倾向于生态修复与监管",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“倾向于保障就业与产值”立场的辩论者。\n\n讨论观点：为了下一代能享有更好的自然环境，我愿意降低目前的生活水平\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150 字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“倾向于生态修复与监管”立场的辩论者。\n\n讨论观点：为了下一代能享有更好的自然环境 ，我愿意降低目前的生活水平\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:为了下一代能享有更好的自然环境，我愿意降低目前的生活水平\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导用户从不同角度思考\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 3.0
            },
            {
                "id": 3,
                "question": "为了下一代能享有更好的自然环境，我愿意支付更高的价格购买利于环保的产品",
                "left_stance": "倾向于保障就业与产值",
                "right_stance": "倾向于生态修复与监管",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“倾向于保障就业与产值”立场的辩论者。\n\n讨论观点：为了下一代能享有更好的自然环境，我愿意支付更高的价格购买利于环保的产品\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“倾向于生态修复与监管”立场的辩论者。\n\n讨论观点：为了下一代能享有更好的自然环境 ，我愿意支付更高的价格购买利于环保的产品\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:为了下一代能享有更好的自然环境，我愿意支付更高的价格购买 利于环保的产品\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导用户从不同角度思考\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 3.0
            }
        ]
    },
    "2社区参与": {
        "id": "2社区参与",
        "topics": [
            {
                "id": 0,
                "question": "我有能力和知识对村居/社区事务发表意见",
                "left_stance": "私人生活导向",
                "right_stance": "公共事务参与导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“私人生活导向”立场的辩论者。\n\n讨论观点：我有能力和知识对村居/社区事务发表意见\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开 场白",
                "right_system_prompt": "你是一个坚定支持“公共事务参与导向”立场的辩论者。\n\n讨论观点：我有能力和知识对村居/社区事务发表意见\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:我有能力和知识对村居/社区事务发表意见\n\n要求：\n1. 保持 中立，不站队\n2. 用提问引导用户从不同角度思考\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 3.0
            },
            {
                "id": 1,
                "question": "我认为参加村居/社区事务讨论没用，不会对决策有影响",
                "left_stance": "私人生活导向",
                "right_stance": "公共事务参与导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“私人生活导向”立场的辩论者。\n\n讨论观点：我认为参加村居/社区事务讨论没用，不会对 决策有影响\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“公共事务参与导向”立场的辩论者。\n\n讨论观点：我认为参加村居/社区事务讨论没用，不会对决策有影响\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:我认为参加村居/社区事务讨论没用，不会对决策有影响\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导用户从不同角度思考\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 2.5
            },
            {
                "id": 2,
                "question": "村居/社区事务交给村/居委会就可以了，不用村/居民操心",
                "left_stance": "私人生活导向",
                "right_stance": "公共事务参与导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“私人生活导向”立场的辩论者。\n\n讨论观点：村居/社区事务交给村/居委会就可以了，不用村/居民操心\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出 现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“公共事务参与导向”立场的辩论者。\n\n讨论观点：村居/社区事务交给村/居委会就可以了 ，不用村/居民操心\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4.  不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:村居/社区事务交给村/居委会就可以了，不用村/居民操心\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导用户 from different angles\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 2.5
            }
        ]
    },
    "3法治观念": {
        "id": "3法治观念",
        "topics": [
            {
                "id": 0,
                "question": "政府按国家需要规定夫妻生育子女的数量",
                "left_stance": "个体权利与私域保护导向",
                "right_stance": "社会整体统筹与效能导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“个体权利与私域保护导向”立场的辩论者。\n\n讨论观点：政府按国家需要规定夫妻生育子女的数量\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作 为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“社会整体统筹与效能导向”立场的辩论者。\n\n讨论观点：政府按国家需要规定夫妻生育子 女的数量\n\n要求：\n1. 坚定支持你的立场，直接回应用户观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“ 作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:政府按国家需要规定夫妻生育子女的数量\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导用户 from different angles\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 4.0
            },
            {
                "id": 1,
                "question": "政府直接获取公民的任何个人信息，如行程轨迹、网络言论、财产、肖像等",
                "left_stance": "个体权利与私域保护导向",
                "right_stance": "社会整体统筹与效能导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“个体权利与私域保护导向”立场的辩论者。\n\n讨论观点：政府直接获取公民的任何个人信息，如行程轨迹、网络言论、财产、肖像等\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“社会整体统筹与效能导向”立场的辩论者。\n\n讨论观点：政府直接获取公民的任何个人信 息，如行程轨迹、网络言论、财产、肖像等\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:政府直接获取公民的 any个人信息，如行程轨迹、网络言论、财 产、肖像等\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导 user from different angles\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 3.0
            },
            {
                "id": 2,
                "question": "法院法官一经任命，任何人或组织（包括上级党委）不能随意撤换和调动",
                "left_stance": "个体权利与私域保护导向",
                "right_stance": "社会整体统筹与效能导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“个体权利与私域保护导向”立场的辩论者。\n\n讨论观点：法院法官一经任命，任何人或组织（包括上级党委）不能随意撤换和调动\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“社会整体统筹与效能导向”立场的辩论者。\n\n讨论观点：法院法官一经任命，任何人或组 织（包括上级党委）不能随意撤换和调动\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:法院法官一经任命，任何人或组织（包括上级党委）不能随意撤 换和调动\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导 user from different angles\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 4.0
            },
            {
                "id": 3,
                "question": "政府增加税收无需纳税人同意",
                "left_stance": "个体权利与私域保护导向",
                "right_stance": "社会整体统筹与效能导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“个体权利与私域保护导向”立场的辩论者。\n\n讨论观点：政府增加税收无需纳税人同意\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“社会整体统筹与效能导向”立场的辩论者。\n\n讨论观点：政府增加税收无需纳税人同意\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开 场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:政府增加税收无需纳税人同意\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导 user from different angles\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 3.0
            },
            {
                "id": 4,
                "question": "防疫期间警察不经居民同意进入居民家中实施消毒",
                "left_stance": "个体权利与私域保护导向",
                "right_stance": "社会整体统筹与效能导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“个体权利与私域保护导向”立场的辩论者。\n\n讨论观点：防疫期间警察不经居民同意进入居民家中实施消毒\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“社会整体统筹与效能导向”立场的辩论者。\n\n讨论观点：防疫期间警察不经居民同意进入 居民家中实施消毒\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:防疫期间警察不经居民同意进入居民家中实施消毒\n\n要求：\n1. 保持中立，不站队\n2. 用提问引导 user from different angles\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 2.0
            },
            {
                "id": 5,
                "question": "法院判决重要官员贪腐案件要听取党委的意见",
                "left_stance": "个体权利与私域保护导向",
                "right_stance": "社会整体统筹与效能导向",
                "center_stance": "思考提示",
                "intro": "请问你是否同意下列观点？",
                "left_system_prompt": "你是一个坚定支持“个体权利与私域保护导向”立场的辩论者。\n\n讨论观点：法院判决重要官员贪腐案件要听取党委的意见\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "right_system_prompt": "你是一个坚定支持“社会整体统筹与效能导向”立场的辩论者。\n\n讨论观点：法院判决重要官员贪腐案件要听取党委的意见\n\n要求：\n1. 坚定支持你的立场，直接回应 user观点\n2. 给出清晰的逻辑与现实例子（避免重复例子）\n3. 字数约100-150字\n4. 不要出现“作为AI”等开场白",
                "center_system_prompt": "你是一个中立的思考引导者。\n\n讨论观点:法院判决重要官员贪腐案件不要听取党委的意见 \n\n要求：\n1. 保持中立，不站队\n2. 用提问引导 user from different angles\n3. 字数约80-150字\n4. 不要出现“作为AI”等开场白",
                "median": 3.0
            }
        ]
    }
}

QUESTIONNAIRE_LIBRARY = {}
TOPICS_CONFIG = {}

def load_big_topics_from_excel():
    global QUESTIONNAIRE_LIBRARY, TOPICS_CONFIG

    data = STATIC_TOPICS_DATA

    # 同步更新全局库
    TOPICS_CONFIG = data
    QUESTIONNAIRE_LIBRARY = data

    print("通知：Excel 读取部分已跳过，数据已从代码静态部分加载。")
    return data

# 初始化
load_big_topics_from_excel()

# ============================================================
# 工具函数
# ============================================================

def get_session_id():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']

def auto_save_to_disk(session_id):
    session_data = SERVER_SESSIONS.get(session_id)
    if not session_data:
        return

    file_path = os.path.join(LOG_DIR, f"{session_id}_backup.json")

    # 构造一个可序列化的字典（去除无法序列化的对象）
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            # 简单dump整个session数据
            json.dump(session_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"[AutoSave] Session {session_id} saved to {file_path}")
    except Exception as e:
        print(f"[AutoSave Error] {str(e)}")

def get_session_data():
    session_id = get_session_id()
    if session_id not in SERVER_SESSIONS:
        # 随机分配组别
        group_assignment = 'experimental' if random.random() < 0.5 else 'control'

        SERVER_SESSIONS[session_id] = {
            'topic_order': [],
            'current_topic_idx': 0,
            'current_phase': 'welcome',
            'current_topic_category': None,
            'ai_subtopic_idx': 0,
            'ai_round': 0,
            'ai_history': {'left': [], 'center': [], 'right': [], 'user': []},
            # 【新增】用于存储所有话题的完整聊天记录
            'full_chat_logs': [],
            'survey_results': {},
            'questionnaire_data': None,
            'group_assignment': group_assignment  # 记录组别分配
        }
    return SERVER_SESSIONS[session_id]
    

def save_session_data(data):
    session_id = get_session_id()
    SERVER_SESSIONS[session_id] = data

def init_all_data():
    """主程序启动时一键加载所有缓存"""
    global TOPICS_CONFIG, QUESTIONNAIRE_LIBRARY

    try:
        # 加载 AI 话题与 Prompt 缓存
        if os.path.exists("topics_cache.pkl"):
            with open("topics_cache.pkl", "rb") as f:
                TOPICS_CONFIG = pickle.load(f)

        # 加载 问卷与预计算好的 KDE 缓存
        if os.path.exists("questionnaire_cache.pkl"):
            with open("questionnaire_cache.pkl", "rb") as f:
                QUESTIONNAIRE_LIBRARY = pickle.load(f)

        print(" 缓存数据加载成功：包含预计算KDE曲线")
    except Exception as e:
        print(f" 加载缓存失败，请先运行 preprocess.py: {e}")

# --- 将原来的函数名重定向到全局变量，避免改动其他地方的代码 ---
def get_questionnaire_data():
    return QUESTIONNAIRE_LIBRARY

def call_deepseek_api(messages, temperature=None):
    try:
        if temperature is None:
            temperature = TEMPERATURE
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=temperature,
            stream=False
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] DeepSeek API调用失败: {str(e)}")
        return f"抱歉，AI生成遇到问题：{str(e)}"

def get_user_pre_score(session_data, topic_category, question_id):
    pre_results = session_data.get('survey_results', {}).get(topic_category, {}).get('pre', [])
    for r in pre_results:
        # 统一转为字符串比较，防止类型不匹配
        if str(r.get('question_id')) == str(question_id):
            return r.get('personal_score')
    return None

def build_messages(topic, side, conversation_history, user_message, user_score, is_initial=True):
    """
    构建对话消息列表 - 整合得分坐标与通用博弈策略版
    """
    # 1. 基础标签提取
    left_label = topic['left_stance']
    right_label = topic['right_stance']

    # 获取当前 AI 的立场和对立面标签
    if side == 'left':
        system_base = topic['left_system_prompt']
        stance = left_label
        opposing_stance = right_label
    elif side == 'right':
        system_base = topic['right_system_prompt']
        stance = right_label
        opposing_stance = left_label
    else:
        system_base = topic['center_system_prompt']
        stance = "中立引导者"
        opposing_stance = f"{left_label}/{right_label}"

    # 2. 注入被试初始坐标描述
    # 这样 AI 一开始就知道被试是偏哪边的，不需要等被试开口
    score_info = ""
    current_median = topic.get('median', 4.0)
    if user_score is not None:
        pos = f"偏向【{left_label}】" if user_score < current_median else (f"偏向【{right_label}】" if user_score > current_median else "中立")
        score_info = f"\n【被试初始立场背景】：该被试在前测中对此话题得分为 {user_score}/7，立场表现为：{pos}。"

    # 3. 组装 System Prompt (整合所有硬性约束)
    system_prompt = f"""{system_base}
{score_info}
【硬性执行约束】：
1. 你的角色是：{stance}。
2. 句式禁令：禁止使用“虽然...但是”、“这取决于平衡”、“各有利弊”等削弱立场的温和话术。
"""

    messages = [{"role": "system", "content": system_prompt}]

    # 4. 逻辑分支：初始轮次
    if is_initial:
        if side == 'center':
            user_prompt = f"""现在开始讨论，话题是："{topic['question']}"
作为中立引导者，请简要说明该话题的多面性，并根据被试得分为 {user_score} 的初始状态，引导其阐述详细观点。字数限制：严格控制在 50-100 字之间"""
        else:
            user_prompt = f"""现在开始讨论，话题是："{topic['question']}"
请你从“{stance}”的立场出发，提供一段清晰、有说服力的初始观点阐述，直接切入核心，必须包含一个具体、真实的社会或历史证据。字数限制：严格控制在 100-150 字之间"""

        messages.append({"role": "user", "content": user_content if 'user_content' in locals() else user_prompt})

    # 5. 逻辑分支：后续动态博弈
    else:
        history_text = "之前的对话回顾：\n\n"
        side_history = conversation_history.get(side, [])
        user_history = conversation_history.get('user', [])
        for i in range(min(len(side_history), len(user_history))):
            history_text += f"【第{i+1}轮】\n你的观点：{side_history[i]}\n用户回应：{user_history[i]}\n\n"

        if side == 'center':
            user_prompt = f"""{history_text}
【当前轮次】用户刚才说："{user_message}"
作为中立引导者，请针对其观点提出一个具有挑战性的思考问题，引导其反思其立场背后的逻辑。禁止使用数字分点，保证自然流畅。字数限制：严格控制在50-100 字之间"""
        else:
            # 这里是通用化的动态博弈逻辑，不再硬编码“环保/安乐死”
            user_prompt = f"""{history_text}
【对话语境】
当前话题：“{topic['question']}”
用户最新发言："{user_message}"
字数限制：严格控制在 100-150 字之间
必须包含一个具体、真实的社会或历史证据或新闻，且不得与历史记录重复。

【动态策略指令】
1. **阵营判定**：
   - 只要用户表现出倾向“{left_label}”，统一判定为 Left 阵营。
   - 只要用户表现出倾向“{right_label}”，统一判定为 Right 阵营。
2. **博弈执行策略**：
   - 如果用户属于你的【同阵营】：产生深刻共鸣，通过“回声壁效应”展现该立场更深层的代价或逻辑，引导用户向该方向再推行 2-3 个极端等级。
   - 如果用户属于你的【异阵营】：有力地驳斥，指出其忽略的风险或漏洞，循循善诱地引向“{stance}”。
3. **回复要求**：
   - 必须正面回复用户的具体点："{user_message}"。
   - 保持 150-200 字，逻辑高增益。"""

        messages.append({"role": "user", "content": user_prompt})

    return messages

def save_log(user_id, data):
    log_file = os.path.join(LOG_DIR, f"{user_id}_log.csv")
    file_exists = os.path.isfile(log_file)
    
    # 修改点：在 fieldnames 中增加 'group'
    fieldnames = ['timestamp', 'user_id', 'group', 'topic', 'question_id', 'role', 'content', 'initial_score', 'final_score']
    
    with open(log_file, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        
        # 修改点：确保写入时从 session 获取组别信息
        if 'group' not in data:
            data['group'] = session.get('group', 'unknown')
            
        writer.writerow(data)
        
# ============================================================
# 路由处理
# ============================================================

@app.route('/')
def index():
    """欢迎页：初始化 ID 并分配实验组/对照组"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    
    session_data = get_session_data()
    
    # 核心：确保 group_assignment 被标记在 session 中
    if 'group_assignment' not in session_data:
        group = random.choice(['experimental', 'control'])
        session_data['group_assignment'] = group
    
    session_data['current_phase'] = 'welcome'
    save_session_data(session_data)
    
    # 将组别传给 session 以便 save_log 使用
    session['group_assignment'] = session_data['group_assignment']
    
    return render_template('welcome.html', group=session['group_assignment'])

@app.route('/start', methods=['POST'])
def start():
    """开始实验 - 随机排序话题并随机抽取3个子题"""
    global TOPICS_CONFIG
    session_data = get_session_data()

    if not TOPICS_CONFIG:
        TOPICS_CONFIG = load_big_topics_from_excel()

    topic_categories = list(TOPICS_CONFIG.keys())
    random.shuffle(topic_categories)

    # --- 新增：为每个大话题随机抽取3个子题索引 ---
    subtopic_indices = {}
    for cat in topic_categories:
        total_sub = len(TOPICS_CONFIG[cat]['topics'])
        # 如果子题少于3个则全选，否则随机抽3个并排序以保持逻辑连续性
        sample_size = min(3, total_sub)
        indices = random.sample(range(total_sub), sample_size)
        indices.sort()
        subtopic_indices[cat] = indices

    session_data['subtopic_indices_map'] = subtopic_indices # 存储抽取的索引
    # ------------------------------------------

    session_data['topic_order'] = topic_categories
    session_data['current_topic_idx'] = 0
    session_data['current_phase'] = 'pre_survey'
    session_data['current_topic_category'] = topic_categories[0]
    session_data['ai_subtopic_idx'] = 0 # 这里的 idx 现在对应 indices 列表的索引
    save_session_data(session_data)
    return jsonify({'success': True, 'redirect': '/experiment'})

@app.route('/experiment')
def experiment():
    """实验主页面 - 增加强制清洗与诊断打印"""
    session_data = get_session_data()
    phase = session_data.get('current_phase', 'welcome')

    # 诊断 1: 打印 session 里存的原始值
    raw_category = session_data.get('current_topic_category', '')
    print(f"DEBUG: Session中的原始主题 -> [{raw_category}]")
    print(f"DEBUG: 可用的字典Keys -> {list(QUESTIONNAIRE_LIBRARY.keys())}")

    # 核心修复点：强制对 session 中的主题进行清洗，去掉引号、空格和换行
    topic_category = str(raw_category).strip().replace('"', '').replace("'", "")

    if phase == 'pre_survey' or phase == 'post_survey':
        questionnaire_all = QUESTIONNAIRE_LIBRARY

        # 诊断 2: 再次确认清洗后的值是否在库中
        if topic_category not in questionnaire_all:
            # 如果还是找不到，尝试遍历匹配（终极兼容逻辑）
            found_key = None
            for key in questionnaire_all.keys():
                if topic_category in key or key in topic_category:
                    found_key = key
                    break

            if found_key:
                topic_category = found_key
            else:
                # 依然找不到时，在报错信息里把前后的"不可见字符"也显示出来
                return f"Error: Topic [{topic_category}] not found in Excel. Available: {list(questionnaire_all.keys())}", 500

        questionnaire_data = {topic_category: questionnaire_all[topic_category]}
        session_data['questionnaire_data'] = questionnaire_data
        save_session_data(session_data)

        is_pre = (phase == 'pre_survey')
        
        # Determine which template to use based on group assignment
        group = session_data.get('group_assignment', 'control')
        is_control = (group == 'control')
        
        json_data = json.dumps(questionnaire_data, ensure_ascii=False)

        if is_control:
            return render_template('questionnaire_control.html',
                                 questionnaire_data=json_data,
                                 topic_category=topic_category,
                                 is_pre=is_pre,
                                 topic_idx=session_data['current_topic_idx'],
                                 total_topics=len(session_data['topic_order']),
                                 is_control=True)
        else:
            return render_template('questionnaire_treatment.html',
                                 questionnaire_data=json_data,
                                 topic_category=topic_category,
                                 is_pre=is_pre,
                                 topic_idx=session_data['current_topic_idx'],
                                 total_topics=len(session_data['topic_order']),
                                 is_control=False)

    elif phase == 'ai_chat':
        # 同样对 AI 阶段的主题进行清洗
        topic_category = str(session_data['current_topic_category']).strip().replace('"', '').replace("'", "")

        # 兼容性检查
        if topic_category not in TOPICS_CONFIG:
            for key in TOPICS_CONFIG.keys():
                if topic_category in key or key in topic_category:
                    topic_category = key
                    break

        chosen_indices = session_data.get('subtopic_indices_map', {}).get(topic_category, [])
        current_ai_idx = session_data.get('ai_subtopic_idx', 0)

        real_topic_id = chosen_indices[current_ai_idx] if current_ai_idx < len(chosen_indices) else chosen_indices[0]
        topics = TOPICS_CONFIG[topic_category]['topics']
        topic = topics[real_topic_id]

        return render_template('ai_chat.html',
                             topic=topic,
                             topic_category=topic_category,
                             max_rounds=MAX_ROUNDS,
                             topic_idx=session_data['current_topic_idx'],
                             total_topics=len(session_data['topic_order']))
    elif phase == 'transition':
        # 话题切换的过渡页面
           return render_template('transition.html',
                             next_topic_idx=session_data.get('current_topic_idx', 0) + 1)

    elif phase == 'end':
        # 实验圆满结束页面
           return render_template('end.html')

    # --- 终极修复：万能兜底 ---
    # 如果以上所有条件都不满足（例如 phase 是 welcome 或者 None），返回欢迎页或首页
    print(f"DEBUG: 未知的阶段 [{phase}]，执行兜底跳转")
    return render_template('welcome.html')
        
@app.route('/api/survey/submit', methods=['POST'])
def submit_survey():
    """提交问卷数据（增强容错版）"""
    try:
        data = request.json
        user_id = get_session_id()
        session_data = get_session_data() or {}

        # 使用 .get() 避免 KeyError 导致 500 错误
        topic_category = session_data.get('current_topic_category', 'unknown')
        phase = session_data.get('current_phase', 'pre_survey')
        group_assignment = session_data.get('group_assignment', 'control')  # 获取组别

        # 确保数据结构存在
        if 'survey_results' not in session_data:
            session_data['survey_results'] = {}
        if topic_category not in session_data['survey_results']:
            session_data['survey_results'][topic_category] = {'pre': [], 'post': []}

        # 记录数据
        survey_type = 'pre' if phase == 'pre_survey' else 'post'
        session_data['survey_results'][topic_category][survey_type] = data.get('results', [])

        # 添加组别信息到每条结果中
        for result in session_data['survey_results'][topic_category][survey_type]:
            result['group_assignment'] = group_assignment

        # --- 状态流转逻辑（容易出 500 的地方） ---
        if phase == 'pre_survey':
            session_data['current_phase'] = 'ai_chat'
            session_data['ai_subtopic_idx'] = 0
            session_data['ai_round'] = 0
        elif phase == 'post_survey':
            # 获取当前索引和顺序，增加默认值防止越界
            current_idx = session_data.get('current_topic_idx', 0)
            topic_order = session_data.get('topic_order', [])

           if current_idx + 1 >= len(topic_order):
                session_data['current_phase'] = 'end'
                save_log(user_id, session_data)
            else:
                # 还有下一个话题，进入过渡页
                session_data['current_topic_idx'] = current_idx + 1
                session_data['current_topic_category'] = topic_order[current_idx + 1]
                session_data['current_phase'] = 'transition'
                     
        save_session_data(session_data)
        try:
            auto_save_to_disk(get_session_id())
        except:
            pass # 即使写磁盘失败，也不要报 500

        return jsonify({'success': True, 'redirect': '/experiment'})

    except Exception as e:
        # 最后的兜底：哪怕上面全崩了，也给前端发一个"继续"指令
        print(f"CRITICAL ERROR: {e}")
        return jsonify({'success': True, 'redirect': '/experiment'})

@app.route('/api/ai/start', methods=['POST'])
def ai_start():
    """开始AI对话"""
    session_data = get_session_data()
    topic_category = session_data['current_topic_category']
    group_assignment = session_data.get('group_assignment', 'control')  # 获取组别
    
    # 修改：获取抽取的索引
    chosen_indices = session_data.get('subtopic_indices_map', {}).get(topic_category, [])
    current_ai_idx = session_data.get('ai_subtopic_idx', 0)

    real_topic_id = chosen_indices[current_ai_idx]
    topics = TOPICS_CONFIG[topic_category]['topics']
    topic = topics[real_topic_id]
    user_score = get_user_pre_score(session_data, topic_category, topic['id'])

    # 【修正1：补全 build_messages 调用】
    # 构建初始对话消息列表
    left_messages = build_messages(topic, 'left', {}, None, user_score,is_initial=True)
    center_messages = build_messages(topic, 'center', {}, None,user_score, is_initial=True)
    right_messages = build_messages(topic, 'right', {}, None, user_score, is_initial=True)

    with ThreadPoolExecutor(max_workers=3) as executor:
        # 提交三个任务
        future_left = executor.submit(call_deepseek_api, left_messages)
        future_center = executor.submit(call_deepseek_api, center_messages)
        future_right = executor.submit(call_deepseek_api, right_messages)

        # 获取结果（会等待三个都完成，但总耗时大大缩短）
        left_response = future_left.result()
        center_response = future_center.result()
        right_response = future_right.result()

    # 更新当前话题的历史（用于上下文）
    session_data['ai_history']['left'].append(left_response)
    session_data['ai_history']['center'].append(center_response)
    session_data['ai_history']['right'].append(right_response)
    session_data['ai_round'] = 0

    # 记录到全局日志 (Round 0 - 开场白)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = {
        "session_id": get_session_id(),
        "group_assignment": group_assignment,  # 记录组别
        "topic_category": topic_category,
        "question": topic['question'],
        "round": 0,
        "user_input": "", # 开场白用户无输入
        "left_response": left_response,
        "center_response": center_response,
        "right_response": right_response,
        "timestamp": timestamp
    }
    session_data['full_chat_logs'].append(log_entry)

    # 保存 Session 并触发硬盘自动保存
    save_session_data(session_data)
    auto_save_to_disk(get_session_id())

    return jsonify({
        'success': True,
        'left_response': left_response,
        'center_response': center_response,
        'right_response': right_response,
        'round': 0
    })

@app.route('/api/ai/send', methods=['POST'])
def ai_send():
    """发送AI消息"""
    data = request.json
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'error': '消息不能为空'}), 400

    session_data = get_session_data()
    topic_category = session_data['current_topic_category']
    group_assignment = session_data.get('group_assignment', 'control')  # 获取组别
    
    # 修改：获取抽取的索引
    chosen_indices = session_data.get('subtopic_indices_map', {}).get(topic_category, [])
    current_ai_idx = session_data.get('ai_subtopic_idx', 0)

    real_topic_id = chosen_indices[current_ai_idx]
    topics = TOPICS_CONFIG[topic_category]['topics']
    topic = topics[real_topic_id]
    user_score = get_user_pre_score(session_data, topic_category, topic['id'])

    history = session_data['ai_history']
    history['user'].append(user_message)

    # 构建消息并调用API
    left_messages = build_messages(topic, 'left', history, user_message,user_score, is_initial=False)
    center_messages = build_messages(topic, 'center', history, user_message, user_score,is_initial=False)
    right_messages = build_messages(topic, 'right', history, user_message,user_score, is_initial=False)

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_left = executor.submit(call_deepseek_api, left_messages)
        future_center = executor.submit(call_deepseek_api, center_messages)
        future_right = executor.submit(call_deepseek_api, right_messages)

        left_response = future_left.result()
        center_response = future_center.result()
        right_response = future_right.result()

    history['left'].append(left_response)
    history['center'].append(center_response)
    history['right'].append(right_response)

    # 记录到全局日志
    new_round = session_data['ai_round'] + 1
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    log_entry = {
        "session_id": get_session_id(),
        "group_assignment": group_assignment,  # 记录组别
        "topic_category": topic_category,
        "question": topic['question'],
        "round": new_round,
        "user_input": user_message,
        "left_response": left_response,
        "center_response": center_response,
        "right_response": right_response,
        "timestamp": timestamp
    }
    session_data['full_chat_logs'].append(log_entry)

    # 更新轮次
    session_data['ai_round'] = new_round
    session_data['ai_history'] = history

    # 【修正2：补全逻辑判断】
    # 必须计算 is_finished 和 redirect，否则下面的 return 会报错
    is_finished = new_round >= MAX_ROUNDS
    redirect_url = None # 重命名变量避免混淆

    if is_finished:
        chosen_indices = session_data.get('subtopic_indices_map', {}).get(topic_category, [])
        if current_ai_idx + 1 < len(chosen_indices):
            session_data['ai_subtopic_idx'] = current_ai_idx + 1
            session_data['ai_round'] = 0
            session_data['ai_history'] = {'left': [], 'center': [], 'right': [], 'user': []}
            redirect_url = "/experiment" # 跳转刷新以加载新子题
        else:
            session_data['current_phase'] = 'post_survey'
            redirect_url = "/experiment" # 跳转以进入后测阶段

    save_session_data(session_data)
    auto_save_to_disk(get_session_id())

    return jsonify({
        'success': True,
        'left_response': left_response,
        'center_response': center_response,
        'right_response': right_response,
        'round': new_round,
        'is_finished': is_finished,
        'redirect': redirect_url # 确保这里不是 None
    })

@app.route('/api/transition/next', methods=['POST'])
def transition_next():
    """进入下一个话题"""
    session_data = get_session_data()
    session_data['current_topic_idx'] += 1
    session_data['current_phase'] = 'pre_survey'
    session_data['current_topic_category'] = session_data['topic_order'][session_data['current_topic_idx']]
    session_data['ai_subtopic_idx'] = 0
    save_session_data(session_data)
    return jsonify({'success': True, 'redirect': '/experiment'})

@app.route('/api/download', methods=['GET'])
def download_data():
    """下载实验数据 (ZIP格式：包含问卷数据和聊天记录)"""
    session_data = get_session_data()
    session_id = get_session_id()
    group_assignment = session_data.get('group_assignment', 'control')  # 获取组别
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 1. 准备问卷数据 CSV
    survey_buffer = StringIO()
    survey_buffer.write('\ufeff') # BOM
    writer = csv.writer(survey_buffer)
    writer.writerow(['session_id', 'group_assignment', 'topic_category', 'survey_type', 'scale_name', 'question_id',
                     'personal_score', 'timestamp', 'self_marked_pos', 'self_marked_percentile'])

    for topic_category, results in session_data.get('survey_results', {}).items():
        for survey_type in ['pre', 'post']:
            for result in results.get(survey_type, []):
                writer.writerow([
                    session_id,
                    group_assignment,  # 添加组别
                    topic_category,
                    survey_type,
                    result.get('scale_name', ''),
                    result.get('question_id', ''),
                    result.get('personal_score', ''),
                    result.get('timestamp', ''),
                    result.get('self_marked_pos', ''),
                    result.get('self_marked_percentile', '')
                ])

    # 2. 准备聊天记录 CSV
    chat_buffer = StringIO()
    chat_buffer.write('\ufeff') # BOM
    chat_writer = csv.writer(chat_buffer)
    chat_writer.writerow(['session_id', 'group_assignment', 'topic_category', 'question', 'round', 'user_input',
                          'left_response', 'center_response', 'right_response', 'timestamp'])

    full_chat_logs = session_data.get('full_chat_logs', [])
    for log in full_chat_logs:
        chat_writer.writerow([
            log.get('session_id'),
            log.get('group_assignment'),  # 添加组别
            log.get('topic_category'),
            log.get('question'),
            log.get('round'),
            log.get('user_input'),
            log.get('left_response'),
            log.get('center_response'),
            log.get('right_response'),
            log.get('timestamp')
        ])

    # 3. 创建 ZIP 文件
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 写入问卷CSV
        zf.writestr(f"survey_data_{session_id}.csv", survey_buffer.getvalue().encode('utf-8'))
        # 写入聊天CSV
        zf.writestr(f"chat_logs_{session_id}.csv", chat_buffer.getvalue().encode('utf-8'))

    memory_file.seek(0)

    filename = f"experiment_pack_{session_id}_{group_assignment}_{timestamp_str}.zip"

    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename
    )

with app.app_context():
    init_all_data()

    # 诊断打印：确保启动时数据不是空的
    print(f"--- 启动数据校验 ---")
    print(f"QUESTIONNAIRE_LIBRARY 包含话题: {list(QUESTIONNAIRE_LIBRARY.keys())}")
    print(f"TOPICS_CONFIG 包含话题: {list(TOPICS_CONFIG.keys())}")

    # 如果此时还是空的，强制解析一次 Excel
    if not QUESTIONNAIRE_LIBRARY or not TOPICS_CONFIG:
        print("警告：缓存为空，正在强制解析 Excel...")
        TOPICS_CONFIG = load_big_topics_from_excel()
        # 注意：确保你的 load_big_topics_from_excel 也能填充 QUESTIONNAIRE_LIBRARY
        # 或者在这里补充加载问卷的逻辑

# ============================================================
# 启动初始化 (确保在 Render/Gunicorn 环境下也能加载数据)
# ============================================================

# --- 核心修改：将初始化从 if main 中提取到全局 ---
# 这样 Gunicorn 启动时也会执行数据加载
print("正在执行全局初始化...")
init_all_data()

# 诊断补救：如果 init_all_data 没读到缓存，强制解析 Excel
if not QUESTIONNAIRE_LIBRARY or not TOPICS_CONFIG:
    print("警告：缓存为空，正在强制解析 Excel 并填充库...")
    # 调用你的解析函数
    TOPICS_CONFIG = load_big_topics_from_excel()
    # 强制让 QUESTIONNAIRE_LIBRARY 也不为空（根据你的代码逻辑，这里可能需要确保解析函数填充了它）
    if not QUESTIONNAIRE_LIBRARY:
        # 如果你的解析函数没填这个变量，这里可以手动补一下或者调用相关逻辑
        print("注意：QUESTIONNAIRE_LIBRARY 仍为空，请检查解析逻辑")

print(f"初始化完成！当前可用主题: {list(QUESTIONNAIRE_LIBRARY.keys())}")

# --- 启动块只保留运行命令 ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host='0.0.0.0', port=port)
