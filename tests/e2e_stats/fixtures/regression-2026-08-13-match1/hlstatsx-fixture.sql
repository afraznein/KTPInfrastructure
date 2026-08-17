-- MySQL dump 10.13  Distrib 8.0.46, for Linux (x86_64)
--
-- Host: localhost    Database: hlstatsx_test
-- ------------------------------------------------------
-- Server version	8.0.46-0ubuntu0.24.04.3

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `geoLiteCity_Blocks`
--

DROP TABLE IF EXISTS `geoLiteCity_Blocks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `geoLiteCity_Blocks` (
  `startIpNum` bigint unsigned NOT NULL DEFAULT '0',
  `endIpNum` bigint unsigned NOT NULL DEFAULT '0',
  `locId` bigint unsigned NOT NULL DEFAULT '0'
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `geoLiteCity_Blocks`
--

LOCK TABLES `geoLiteCity_Blocks` WRITE;
/*!40000 ALTER TABLE `geoLiteCity_Blocks` DISABLE KEYS */;
/*!40000 ALTER TABLE `geoLiteCity_Blocks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `geoLiteCity_Location`
--

DROP TABLE IF EXISTS `geoLiteCity_Location`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `geoLiteCity_Location` (
  `locId` bigint unsigned NOT NULL DEFAULT '0',
  `country` varchar(2) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `region` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `city` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `postalCode` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `latitude` decimal(14,4) DEFAULT NULL,
  `longitude` decimal(14,4) DEFAULT NULL,
  PRIMARY KEY (`locId`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `geoLiteCity_Location`
--

LOCK TABLES `geoLiteCity_Location` WRITE;
/*!40000 ALTER TABLE `geoLiteCity_Location` DISABLE KEYS */;
/*!40000 ALTER TABLE `geoLiteCity_Location` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Actions`
--

DROP TABLE IF EXISTS `hlstats_Actions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Actions` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'valve',
  `code` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `reward_player` int NOT NULL DEFAULT '10',
  `reward_team` int NOT NULL DEFAULT '0',
  `team` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `description` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `for_PlayerActions` enum('0','1') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  `for_PlayerPlayerActions` enum('0','1') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  `for_TeamActions` enum('0','1') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  `for_WorldActions` enum('0','1') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  `count` int unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `gamecode` (`code`,`game`,`team`),
  KEY `code` (`code`)
) ENGINE=MyISAM AUTO_INCREMENT=724 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Actions`
--

LOCK TABLES `hlstats_Actions` WRITE;
/*!40000 ALTER TABLE `hlstats_Actions` DISABLE KEYS */;
INSERT INTO `hlstats_Actions` (`id`, `game`, `code`, `reward_player`, `reward_team`, `team`, `description`, `for_PlayerActions`, `for_PlayerPlayerActions`, `for_TeamActions`, `for_WorldActions`, `count`) VALUES (722,'dod','assist',0,0,'','Assists','0','1','0','0',57);
INSERT INTO `hlstats_Actions` (`id`, `game`, `code`, `reward_player`, `reward_team`, `team`, `description`, `for_PlayerActions`, `for_PlayerPlayerActions`, `for_TeamActions`, `for_WorldActions`, `count`) VALUES (723,'dod','cap_break',0,0,'','Cap Breaks','1','0','0','0',3);
/*!40000 ALTER TABLE `hlstats_Actions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Awards`
--

DROP TABLE IF EXISTS `hlstats_Awards`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Awards` (
  `awardId` int unsigned NOT NULL AUTO_INCREMENT,
  `awardType` char(1) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'W',
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'valve',
  `code` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `verb` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `d_winner_id` int unsigned DEFAULT NULL,
  `d_winner_count` int unsigned DEFAULT NULL,
  `g_winner_id` int unsigned DEFAULT NULL,
  `g_winner_count` int unsigned DEFAULT NULL,
  PRIMARY KEY (`awardId`),
  UNIQUE KEY `code` (`game`,`awardType`,`code`)
) ENGINE=MyISAM AUTO_INCREMENT=956 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Awards`
--

LOCK TABLES `hlstats_Awards` WRITE;
/*!40000 ALTER TABLE `hlstats_Awards` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Awards` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_ClanTags`
--

DROP TABLE IF EXISTS `hlstats_ClanTags`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_ClanTags` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `pattern` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `position` enum('EITHER','START','END') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'EITHER',
  PRIMARY KEY (`id`),
  UNIQUE KEY `pattern` (`pattern`)
) ENGINE=MyISAM AUTO_INCREMENT=30 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_ClanTags`
--

LOCK TABLES `hlstats_ClanTags` WRITE;
/*!40000 ALTER TABLE `hlstats_ClanTags` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_ClanTags` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Clans`
--

DROP TABLE IF EXISTS `hlstats_Clans`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Clans` (
  `clanId` int unsigned NOT NULL AUTO_INCREMENT,
  `tag` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `homepage` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `hidden` tinyint unsigned NOT NULL DEFAULT '0',
  `mapregion` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  PRIMARY KEY (`clanId`),
  UNIQUE KEY `tag` (`game`,`tag`),
  KEY `game` (`game`)
) ENGINE=MyISAM AUTO_INCREMENT=161 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Clans`
--

LOCK TABLES `hlstats_Clans` WRITE;
/*!40000 ALTER TABLE `hlstats_Clans` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Clans` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Countries`
--

DROP TABLE IF EXISTS `hlstats_Countries`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Countries` (
  `flag` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`flag`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Countries`
--

LOCK TABLES `hlstats_Countries` WRITE;
/*!40000 ALTER TABLE `hlstats_Countries` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Countries` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Admin`
--

DROP TABLE IF EXISTS `hlstats_Events_Admin`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Admin` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `type` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'Unknown',
  `message` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerName` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=161 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Admin`
--

LOCK TABLES `hlstats_Events_Admin` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Admin` DISABLE KEYS */;
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (1,'2026-08-13 03:07:01',1,'','AMXX (ktp_file)','[KTP File Checker] Loaded 0 file consistency checks from ktp_file.ini','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (2,'2026-08-13 03:07:02',1,'','AMXX (ktp_cvar)','[KTP Cvar Checker] Pre-converted 44 cvar values to floats','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (3,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=TEAMSCORE_MSG_REGISTERED msgid=69','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (4,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=ROUNDSTATE_MSG_REGISTERED msgid=66','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (5,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] Registered RH_PF_changelevel_I hook (KTP-ReHLDS mode)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (6,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] Registered RH_Host_Changelevel_f hook (KTP-ReHLDS mode)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (7,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=CHANGELEVEL_HOOKS_REGISTERED pfn=1 host=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (8,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] Registered RH_SV_UpdatePausedHUD hook (KTP-ReHLDS mode)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (9,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_CACHED full=\'Half-Life\' base=\'Half-Life\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (10,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP-TEST-MODE] test-mode RCON commands registered (KTP_TEST_MODE build)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (11,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','performance issue. Function plugin_init executed more than 1.0ms.','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (12,'2026-08-13 03:07:02',1,'','AMXX (KTPGrenadeLoadout)','[KTPGrenadeLoadout] Loaded 0 class grenade settings from config','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (13,'2026-08-13 03:07:02',1,'','AMXX (KTPBreakDrive)','[MD] loaded — NOT FOR PRODUCTION','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (14,'2026-08-13 03:07:02',1,'','AMXX (KTPAdminAudit)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (15,'2026-08-13 03:07:02',1,'','AMXX (KTPAdminAudit)','[KTP] Loaded 6 maps from addons/ktpamx/configs/ktp_maps.ini','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (16,'2026-08-13 03:07:02',1,'','AMXX (ktp_cvar)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (17,'2026-08-13 03:07:02',1,'','AMXX (ktp_file)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (18,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=PLUGIN_ENABLED name=\'KTP Match Handler\' version=0.10.155 author=\'Nein_\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (19,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_CACHED full=\'Half-Life\' base=\'Half-Life\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (20,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=KTP_CONFIG_LOAD status=ok loaded=2 season=INACTIVE password_set=yes path=\'addons/ktpamx/configs/ktp.ini\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (21,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=MAPS_LOAD status=ok count=32 path=\'addons/ktpamx/configs/ktp_maps.ini\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (22,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=DISCORD_CONFIG_LOAD status=ok loaded=0 path=\'addons/ktpamx/configs/discord.ini\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (23,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (24,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=AC_CONFIG_LOAD status=skip reason=\'file_not_found\' path=\'addons/ktpamx/configs/ac.ini\' (AC integration disabled)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (25,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=AC_SERVER_ENDPOINT endpoint=127.0.0.1:27050','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (26,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=DODX_STATS_NATIVES status=available','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (27,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=CONTEXT_CHECK mode=\'\' current_map=dod_anzio','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (28,'2026-08-13 03:07:02',1,'','AMXX (KTPMatchHandler)','[KTP] event=TEAM_NAMES_RESET reason=no_pending_mode','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (29,'2026-08-13 03:07:02',1,'','AMXX (KTPHLTVRecorder)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (30,'2026-08-13 03:07:02',1,'','AMXX (KTPGrenadeLoadout)','[KTPGrenadeLoadout] Loaded 0 class grenade settings from config','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (31,'2026-08-13 03:07:02',1,'','AMXX (KTPAdminAudit)','[KTP Admin Audit] v2.7.18 initialized (changelevel hook active)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (32,'2026-08-13 03:07:03',1,'','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_CACHED_DELAYED full=\'KTP Smoke Test\' base=\'KTP Smoke Test\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (33,'2026-08-13 03:07:03',1,'','AMXX (KTPPracticeMode)','[KTPPracticeMode] Hostname cached (delayed): KTP Smoke Test','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (34,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=1 name=Bishop team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (35,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=2 name=Ash team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (36,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=3 name=Cutter team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (37,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=4 name=Burke team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (38,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=5 name=Dallas team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (39,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=6 name=Ferro team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (40,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=7 name=Pyramid team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (41,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=8 name=Hicks team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (42,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=9 name=Dracula team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (43,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=10 name=Hudson team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (44,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=11 name=Kane team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (45,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=12 name=Claire team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (46,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=13 name=Lambert team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (47,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=14 name=Ripley team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (48,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] player id=15 name=Parker team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (49,'2026-08-13 03:07:42',1,'','AMXX (KTPBreakDrive)','[MD] roster allies=7 axis=8 total=15','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (50,'2026-08-13 03:07:45',1,'','AMXX (KTPMatchHandler)','[KTP] event=TEST_SETUP matchType=0 map=dod_anzio match_id=1786590465-TEST','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (51,'2026-08-13 03:07:45',1,'','AMXX (KTPMatchHandler)','[KTP] event=TEST_ADVANCE_PENDING match_id=1786590465-TEST map=dod_anzio','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (52,'2026-08-13 03:07:45',1,'','AMXX (KTPMatchHandler)','[KTP] event=PENDING_BEGIN map=dod_anzio need=6','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (53,'2026-08-13 03:07:45',1,'','AMXX (KTPMatchHandler)','[KTP] event=PENDING_ENFORCE initiator=\'test_harness\' map=dod_anzio paused=0 pending=1 live=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (54,'2026-08-13 03:07:46',1,'','AMXX (KTPMatchHandler)','[KTP] event=TEST_ADVANCE_LIVE match_id=1786590465-TEST half=1 map=dod_anzio matchType=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (55,'2026-08-13 03:07:46',1,'','AMXX (KTPMatchHandler)','[KTP] event=DEFERRED_FWD_SCHEDULED src=test_advance_live frame=44.637 match_id=1786590465-TEST','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (56,'2026-08-13 03:07:46',1,'','AMXX (KTPMatchHandler)','[KTP] event=DEFERRED_FWD_FIRED match_id=1786590465-TEST src=test_advance_live frame=44.886','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (57,'2026-08-13 03:07:46',1,'','AMXX (KTPMatchHandler)','[KTP] event=ROSTER_SNAPSHOT team1=0 team2=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (58,'2026-08-13 03:07:46',1,'','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_UPDATE hostname=\'KTP Smoke Test - KTP - PENDING\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (59,'2026-08-13 03:07:46',1,'','AMXX (KTPHLTVRecorder)','[KTP HLTV] MATCH_WINDOW_OPEN match_id=1786590465-TEST half=h1 match_type=ktp map=dod_anzio hltv_port=27020 wall_time=1786590466 enabled=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (60,'2026-08-13 03:07:46',1,'','AMXX (KTPMatchHandler)','[KTP] event=FWD_MATCH_START match_id=1786590465-TEST map=dod_anzio type=0 half=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (61,'2026-08-13 03:07:46',1,'','AMXX (KTPMatchHandler)','[KTP] event=PROACTIVE_CONTEXT_SAVE match_id=1786590465-TEST map=dod_anzio half=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (62,'2026-08-13 03:07:46',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=ROUNDLIVE_MATCH_START_LOG matchid=1786590465-TEST map=dod_anzio half=1st','','1786590465-TEST');
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (63,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=TEST_END_FIRST_HALF match_id=1786590465-TEST scores=2-1','','1786590465-TEST');
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (64,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=STATS_FLUSH type=half1 players=15 match_id=1786590465-TEST','','1786590465-TEST');
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (65,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=MATCH_ID_CLEARED reason=halftime','','1786590465-TEST');
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (66,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=SCORE_FROM_DODX_SKIPPED reason=no_gamerules half=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (67,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=FIRST_HALF_SCORES_SAVED team1=2 team2=1 (persisted to localinfo)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (68,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=HALF_END half=1st map=dod_anzio next_map=dod_anzio match_id=1786590465-TEST score=Allies_2-1_Axis','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (69,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=ROSTER_SAVED_LOCALINFO team1=0 team2=0 chunked=1 failed=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (70,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=MATCH_CONTEXT_SAVED match_id=1786590465-TEST state=2,1 h1=2,1 team1=Allies team2=Axis discord_msg= roster1=0 roster2=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (71,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DISCORD_EDIT_SKIP reason=no_msg_id','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (72,'2026-08-13 03:38:35',1,'dod_anzio','AMXX (KTPMatchHandler)','performance issue. Function cmd_test_end_first_half executed more than 1.1ms.','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (73,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=CHANGELEVEL_HOOK_FIRED map=dod_anzio matchLive=1 half=1 handled=0 inOT=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (74,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=CHANGELEVEL_FIRST_HALF original_map=dod_anzio matchId=1786590465-TEST g_matchMap=dod_anzio g_currentMap=dod_anzio','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (75,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=STATS_FLUSH type=half1 players=15 match_id=1786590465-TEST','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (76,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=MATCH_ID_CLEARED reason=halftime','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (77,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=SCORE_FROM_DODX_SKIPPED reason=no_gamerules half=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (78,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=FIRST_HALF_SCORES_SAVED team1=2 team2=1 (persisted to localinfo)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (79,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=HALF_END half=1st map=dod_anzio next_map=dod_anzio match_id=1786590465-TEST score=Allies_2-1_Axis','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (80,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=ROSTER_SAVED_LOCALINFO team1=0 team2=0 chunked=1 failed=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (81,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=MATCH_CONTEXT_SAVED match_id=1786590465-TEST state=2,1 h1=2,1 team1=Allies team2=Axis discord_msg= roster1=0 roster2=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (82,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DISCORD_EDIT_SKIP reason=no_msg_id','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (83,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=CHANGELEVEL_REDIRECT before_redirect=dod_anzio target=dod_anzio','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (84,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=PLUGIN_END_START half=1 matchLive=1 matchId=1786590465-TEST changeLevelHandled=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (85,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=PLUGIN_END_COMPLETE','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (86,'2026-08-13 03:38:36',1,'dod_anzio','AMXX (ktp_file)','[KTP File Checker] Loaded 0 file consistency checks from ktp_file.ini','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (87,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (ktp_cvar)','[KTP Cvar Checker] Pre-converted 44 cvar values to floats','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (88,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=TEAMSCORE_MSG_REGISTERED msgid=69','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (89,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=ROUNDSTATE_MSG_REGISTERED msgid=66','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (90,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] Registered RH_PF_changelevel_I hook (KTP-ReHLDS mode)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (91,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] Registered RH_Host_Changelevel_f hook (KTP-ReHLDS mode)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (92,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=CHANGELEVEL_HOOKS_REGISTERED pfn=1 host=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (93,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] Registered RH_SV_UpdatePausedHUD hook (KTP-ReHLDS mode)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (94,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_CACHED full=\'KTP Smoke Test - KTP - PENDING\' base=\'KTP Smoke Test\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (95,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP-TEST-MODE] test-mode RCON commands registered (KTP_TEST_MODE build)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (96,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPGrenadeLoadout)','[KTPGrenadeLoadout] Loaded 0 class grenade settings from config','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (97,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] loaded — NOT FOR PRODUCTION','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (98,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPAdminAudit)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (99,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPAdminAudit)','[KTP] Loaded 6 maps from addons/ktpamx/configs/ktp_maps.ini','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (100,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (ktp_cvar)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (101,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (ktp_file)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (102,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=PLUGIN_ENABLED name=\'KTP Match Handler\' version=0.10.155 author=\'Nein_\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (103,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_CACHED full=\'KTP Smoke Test - KTP - PENDING\' base=\'KTP Smoke Test\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (104,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=KTP_CONFIG_LOAD status=ok loaded=2 season=INACTIVE password_set=yes path=\'addons/ktpamx/configs/ktp.ini\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (105,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=MAPS_LOAD status=ok count=32 path=\'addons/ktpamx/configs/ktp_maps.ini\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (106,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DISCORD_CONFIG_LOAD status=ok loaded=0 path=\'addons/ktpamx/configs/discord.ini\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (107,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (108,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=AC_CONFIG_LOAD status=skip reason=\'file_not_found\' path=\'addons/ktpamx/configs/ac.ini\' (AC integration disabled)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (109,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=AC_SERVER_ENDPOINT endpoint=127.0.0.1:27050','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (110,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DODX_STATS_NATIVES status=available','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (111,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=CONTEXT_CHECK mode=\'h2\' current_map=dod_anzio','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (112,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=CAPTAINS_RESTORED captain1=\'test_captain_allies\' sid1=STEAM_0:0:11111111 captain2=\'test_captain_axis\' sid2=STEAM_0:0:22222222','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (113,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=ROSTER_RESTORED_LOCALINFO team1=0 team2=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (114,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=MATCH_CONTEXT_RESTORED mode=h2 match_id=1786590465-TEST map=dod_anzio state=0,0,0,0 h1=2,1 team1=Allies team2=Axis matchPending=1 roster1=0 roster2=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (115,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','performance issue. Function plugin_cfg executed more than 1.1ms.','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (116,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPHLTVRecorder)','[KTP Discord] Missing required config (url=0, auth=0, channel=0)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (117,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPGrenadeLoadout)','[KTPGrenadeLoadout] Loaded 0 class grenade settings from config','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (118,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPAdminAudit)','[KTP Admin Audit] v2.7.18 initialized (changelevel hook active)','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (119,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_CACHED_DELAYED full=\'KTP Smoke Test - KTP - PENDING\' base=\'KTP Smoke Test\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (120,'2026-08-13 03:38:37',1,'dod_anzio','AMXX (KTPPracticeMode)','[KTPPracticeMode] Hostname cached (delayed): KTP Smoke Test','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (121,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=1 name=Crash team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (122,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=2 name=GLaDOS team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (123,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=3 name=Ash team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (124,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=4 name=Bishop team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (125,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=5 name=Burke team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (126,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=6 name=Cutter team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (127,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=7 name=Ferro team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (128,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=8 name=Dallas team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (129,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=9 name=Hudson team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (130,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=10 name=Hicks team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (131,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=11 name=Lambert team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (132,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=12 name=Kane team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (133,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=13 name=Parker team=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (134,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] player id=14 name=Ripley team=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (135,'2026-08-13 03:39:26',1,'dod_anzio','AMXX (KTPBreakDrive)','[MD] roster allies=7 axis=7 total=14','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (136,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=TEST_ADVANCE_LIVE match_id=1786590465-TEST half=2 map=dod_anzio matchType=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (137,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DEFERRED_FWD_SCHEDULED src=test_advance_live frame=53.906 match_id=1786590465-TEST','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (138,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DEFERRED_FWD_FIRED match_id=1786590465-TEST src=test_advance_live frame=54.189','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (139,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=ROSTER_SNAPSHOT team1=0 team2=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (140,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_UPDATE hostname=\'KTP Smoke Test - KTP - PENDING\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (141,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DISCORD_EDIT_SKIP reason=no_msg_id','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (142,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPHLTVRecorder)','[KTP HLTV] MATCH_WINDOW_OPEN match_id=1786590465-TEST half=h2 match_type=ktp map=dod_anzio hltv_port=27020 wall_time=1786592369 enabled=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (143,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=FWD_MATCH_START match_id=1786590465-TEST map=dod_anzio type=0 half=2','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (144,'2026-08-13 03:39:29',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=ROUNDLIVE_MATCH_START_LOG matchid=1786590465-TEST map=dod_anzio half=2nd','','1786590465-TEST');
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (145,'2026-08-13 04:00:34',1,'dod_anzio','AMXX (stats_logging)','performance issue. Function ksc_flush_task executed more than 2.5ms.','','1786590465-TEST');
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (146,'2026-08-13 04:01:17',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=TEST_END_MATCH match_id=1786590465-TEST final=2-3','','1786590465-TEST');
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (147,'2026-08-13 04:01:17',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DISCORD_EDIT_SKIP reason=no_msg_id','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (148,'2026-08-13 04:01:17',1,'dod_anzio','AMXX (KTPHLTVRecorder)','[KTP HLTV] MATCH_WINDOW_CLOSE match_id=1786590465-TEST match_type=ktp map=dod_anzio hltv_port=27020 wall_time=1786593677 score=2-3','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (149,'2026-08-13 04:01:18',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=TEST_SETUP matchType=0 map=dod_anzio match_id=1786593678-TEST','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (150,'2026-08-13 04:01:18',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=TEST_ADVANCE_PENDING match_id=1786593678-TEST map=dod_anzio','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (151,'2026-08-13 04:01:18',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=PENDING_BEGIN map=dod_anzio need=6','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (152,'2026-08-13 04:01:18',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=PENDING_ENFORCE initiator=\'test_harness\' map=dod_anzio paused=0 pending=1 live=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (153,'2026-08-13 04:01:18',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=TEST_ADVANCE_LIVE match_id=1786593678-TEST half=1 map=dod_anzio matchType=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (154,'2026-08-13 04:01:18',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DEFERRED_FWD_SCHEDULED src=test_advance_live frame=1260.975 match_id=1786593678-TEST','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (155,'2026-08-13 04:01:19',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=DEFERRED_FWD_FIRED match_id=1786593678-TEST src=test_advance_live frame=1261.206','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (156,'2026-08-13 04:01:19',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=ROSTER_SNAPSHOT team1=0 team2=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (157,'2026-08-13 04:01:19',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=HOSTNAME_UPDATE hostname=\'KTP Smoke Test - KTP - PENDING\'','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (158,'2026-08-13 04:01:19',1,'dod_anzio','AMXX (KTPHLTVRecorder)','[KTP HLTV] MATCH_WINDOW_OPEN match_id=1786593678-TEST half=h1 match_type=ktp map=dod_anzio hltv_port=27020 wall_time=1786593679 enabled=0','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (159,'2026-08-13 04:01:19',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=FWD_MATCH_START match_id=1786593678-TEST map=dod_anzio type=0 half=1','',NULL);
INSERT INTO `hlstats_Events_Admin` (`id`, `eventTime`, `serverId`, `map`, `type`, `message`, `playerName`, `match_id`) VALUES (160,'2026-08-13 04:01:19',1,'dod_anzio','AMXX (KTPMatchHandler)','[KTP] event=PROACTIVE_CONTEXT_SAVE match_id=1786593678-TEST map=dod_anzio half=1','',NULL);
/*!40000 ALTER TABLE `hlstats_Events_Admin` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_ChangeName`
--

DROP TABLE IF EXISTS `hlstats_Events_ChangeName`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_ChangeName` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `oldName` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `newName` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM AUTO_INCREMENT=4869 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_ChangeName`
--

LOCK TABLES `hlstats_Events_ChangeName` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_ChangeName` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_ChangeName` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_ChangeRole`
--

DROP TABLE IF EXISTS `hlstats_Events_ChangeRole`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_ChangeRole` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `role` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM AUTO_INCREMENT=88055 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_ChangeRole`
--

LOCK TABLES `hlstats_Events_ChangeRole` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_ChangeRole` DISABLE KEYS */;
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87917,'2026-08-13 03:07:09',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87918,'2026-08-13 03:07:10',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87919,'2026-08-13 03:07:10',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87920,'2026-08-13 03:07:11',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87921,'2026-08-13 03:07:11',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87922,'2026-08-13 03:07:12',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87923,'2026-08-13 03:07:12',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87924,'2026-08-13 03:07:12',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87925,'2026-08-13 03:07:13',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87926,'2026-08-13 03:07:13',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87927,'2026-08-13 03:07:13',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87928,'2026-08-13 03:07:13',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87929,'2026-08-13 03:07:14',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87930,'2026-08-13 03:07:14',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87931,'2026-08-13 03:07:14',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87932,'2026-08-13 03:07:14',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87933,'2026-08-13 03:07:14',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87934,'2026-08-13 03:07:15',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87935,'2026-08-13 03:07:15',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87936,'2026-08-13 03:07:15',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87937,'2026-08-13 03:07:15',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87938,'2026-08-13 03:07:15',1,'',309,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87939,'2026-08-13 03:07:15',1,'',310,'Random',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87940,'2026-08-13 03:07:15',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87941,'2026-08-13 03:07:16',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87942,'2026-08-13 03:07:16',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87943,'2026-08-13 03:07:16',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87944,'2026-08-13 03:07:16',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87945,'2026-08-13 03:07:16',1,'',309,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87946,'2026-08-13 03:07:16',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87947,'2026-08-13 03:07:16',1,'',311,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87948,'2026-08-13 03:07:17',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87949,'2026-08-13 03:07:17',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87950,'2026-08-13 03:07:17',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87951,'2026-08-13 03:07:17',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87952,'2026-08-13 03:07:17',1,'',309,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87953,'2026-08-13 03:07:17',1,'',312,'Random',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87954,'2026-08-13 03:07:17',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87955,'2026-08-13 03:07:17',1,'',311,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87956,'2026-08-13 03:07:18',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87957,'2026-08-13 03:07:18',1,'',313,'#class_axis_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87958,'2026-08-13 03:07:18',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87959,'2026-08-13 03:07:18',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87960,'2026-08-13 03:07:18',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87961,'2026-08-13 03:07:18',1,'',309,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87962,'2026-08-13 03:07:18',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87963,'2026-08-13 03:07:18',1,'',311,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87964,'2026-08-13 03:07:19',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87965,'2026-08-13 03:07:19',1,'',313,'#class_axis_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87966,'2026-08-13 03:07:19',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87967,'2026-08-13 03:07:19',1,'',314,'#class_allied_mg',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87968,'2026-08-13 03:07:19',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87969,'2026-08-13 03:07:19',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87970,'2026-08-13 03:07:19',1,'',309,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87971,'2026-08-13 03:07:19',1,'',315,'Random',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87972,'2026-08-13 03:07:19',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87973,'2026-08-13 03:07:19',1,'',311,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87974,'2026-08-13 03:07:20',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87975,'2026-08-13 03:07:20',1,'',313,'#class_axis_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87976,'2026-08-13 03:07:20',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87977,'2026-08-13 03:07:20',1,'',314,'#class_allied_mg',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87978,'2026-08-13 03:07:20',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87979,'2026-08-13 03:07:20',1,'',316,'#class_axis_mg34',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87980,'2026-08-13 03:07:20',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87981,'2026-08-13 03:07:20',1,'',309,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87982,'2026-08-13 03:07:20',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87983,'2026-08-13 03:07:20',1,'',311,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87984,'2026-08-13 03:07:21',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87985,'2026-08-13 03:07:21',1,'',313,'#class_axis_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87986,'2026-08-13 03:07:21',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87987,'2026-08-13 03:07:21',1,'',314,'#class_allied_mg',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87988,'2026-08-13 03:07:21',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87989,'2026-08-13 03:07:21',1,'',316,'#class_axis_mg34',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87990,'2026-08-13 03:07:21',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87991,'2026-08-13 03:07:21',1,'',309,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87992,'2026-08-13 03:07:21',1,'',317,'#class_allied_bazooka',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87993,'2026-08-13 03:07:21',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87994,'2026-08-13 03:07:21',1,'',311,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87995,'2026-08-13 03:07:22',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87996,'2026-08-13 03:07:22',1,'',313,'#class_axis_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87997,'2026-08-13 03:07:22',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87998,'2026-08-13 03:07:22',1,'',314,'#class_allied_mg',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (87999,'2026-08-13 03:07:22',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88000,'2026-08-13 03:07:22',1,'',316,'#class_axis_mg34',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88001,'2026-08-13 03:07:22',1,'',304,'#class_allied_carbine',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88002,'2026-08-13 03:07:22',1,'',309,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88003,'2026-08-13 03:07:22',1,'',317,'#class_allied_bazooka',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88004,'2026-08-13 03:07:22',1,'',305,'#class_axis_k43',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88005,'2026-08-13 03:07:22',1,'',311,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88006,'2026-08-13 03:07:22',1,'',318,'#class_axis_pschreck',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88007,'2026-08-13 03:07:23',1,'',306,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88008,'2026-08-13 03:07:23',1,'',313,'#class_axis_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88009,'2026-08-13 03:07:23',1,'',307,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88010,'2026-08-13 03:07:23',1,'',314,'#class_allied_mg',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88011,'2026-08-13 03:07:23',1,'',308,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88012,'2026-08-13 03:07:23',1,'',318,'#class_axis_pschreck',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88013,'2026-08-13 03:07:24',1,'',318,'#class_axis_pschreck',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88014,'2026-08-13 03:07:25',1,'',318,'#class_axis_pschreck',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88015,'2026-08-13 03:07:26',1,'',318,'#class_axis_pschreck',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88016,'2026-08-13 03:07:27',1,'',318,'#class_axis_pschreck',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88017,'2026-08-13 03:38:49',1,'dod_anzio',319,'Random',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88018,'2026-08-13 03:38:51',1,'dod_anzio',320,'Random',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88019,'2026-08-13 03:38:53',1,'dod_anzio',305,'#class_allied_garand',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88020,'2026-08-13 03:38:54',1,'dod_anzio',305,'#class_allied_garand',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88021,'2026-08-13 03:38:54',1,'dod_anzio',304,'#class_axis_kar98',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88022,'2026-08-13 03:38:55',1,'dod_anzio',305,'#class_allied_garand',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88023,'2026-08-13 03:38:55',1,'dod_anzio',304,'#class_axis_kar98',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88024,'2026-08-13 03:38:55',1,'dod_anzio',307,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88025,'2026-08-13 03:38:56',1,'dod_anzio',305,'#class_allied_garand',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88026,'2026-08-13 03:38:56',1,'dod_anzio',304,'#class_axis_kar98',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88027,'2026-08-13 03:38:56',1,'dod_anzio',307,'#class_allied_grease',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88028,'2026-08-13 03:38:56',1,'dod_anzio',306,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88029,'2026-08-13 03:38:57',1,'dod_anzio',306,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88030,'2026-08-13 03:38:58',1,'dod_anzio',309,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88031,'2026-08-13 03:38:58',1,'dod_anzio',306,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88032,'2026-08-13 03:38:59',1,'dod_anzio',309,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88033,'2026-08-13 03:38:59',1,'dod_anzio',308,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88034,'2026-08-13 03:38:59',1,'dod_anzio',306,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88035,'2026-08-13 03:39:00',1,'dod_anzio',309,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88036,'2026-08-13 03:39:00',1,'dod_anzio',308,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88037,'2026-08-13 03:39:00',1,'dod_anzio',313,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88038,'2026-08-13 03:39:00',1,'dod_anzio',306,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88039,'2026-08-13 03:39:01',1,'dod_anzio',309,'#class_allied_heavy',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88040,'2026-08-13 03:39:01',1,'dod_anzio',308,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88041,'2026-08-13 03:39:01',1,'dod_anzio',313,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88042,'2026-08-13 03:39:01',1,'dod_anzio',311,'#class_axis_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88043,'2026-08-13 03:39:01',1,'dod_anzio',306,'#class_axis_mp40',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88044,'2026-08-13 03:39:02',1,'dod_anzio',308,'#class_axis_mp44',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88045,'2026-08-13 03:39:02',1,'dod_anzio',313,'#class_allied_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88046,'2026-08-13 03:39:02',1,'dod_anzio',311,'#class_axis_sniper',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88047,'2026-08-13 03:39:03',1,'dod_anzio',316,'#class_allied_mg',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88048,'2026-08-13 03:39:04',1,'dod_anzio',316,'#class_allied_mg',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88049,'2026-08-13 03:39:04',1,'dod_anzio',314,'#class_axis_mg34',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88050,'2026-08-13 03:39:05',1,'dod_anzio',314,'#class_axis_mg34',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88051,'2026-08-13 03:39:05',1,'dod_anzio',318,'#class_allied_bazooka',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88052,'2026-08-13 03:39:06',1,'dod_anzio',318,'#class_allied_bazooka',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88053,'2026-08-13 03:39:06',1,'dod_anzio',317,'#class_axis_pschreck',NULL);
INSERT INTO `hlstats_Events_ChangeRole` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `role`, `match_id`) VALUES (88054,'2026-08-13 03:39:07',1,'dod_anzio',317,'#class_axis_pschreck',NULL);
/*!40000 ALTER TABLE `hlstats_Events_ChangeRole` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_ChangeTeam`
--

DROP TABLE IF EXISTS `hlstats_Events_ChangeTeam`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_ChangeTeam` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `team` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM AUTO_INCREMENT=429613 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_ChangeTeam`
--

LOCK TABLES `hlstats_Events_ChangeTeam` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_ChangeTeam` DISABLE KEYS */;
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429584,'2026-08-13 03:07:08',1,'',304,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429585,'2026-08-13 03:07:09',1,'',305,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429586,'2026-08-13 03:07:11',1,'',306,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429587,'2026-08-13 03:07:12',1,'',307,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429588,'2026-08-13 03:07:13',1,'',308,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429589,'2026-08-13 03:07:14',1,'',309,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429590,'2026-08-13 03:07:14',1,'',310,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429591,'2026-08-13 03:07:15',1,'',311,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429592,'2026-08-13 03:07:16',1,'',312,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429593,'2026-08-13 03:07:17',1,'',313,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429594,'2026-08-13 03:07:18',1,'',314,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429595,'2026-08-13 03:07:18',1,'',315,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429596,'2026-08-13 03:07:19',1,'',316,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429597,'2026-08-13 03:07:20',1,'',317,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429598,'2026-08-13 03:07:21',1,'',318,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429599,'2026-08-13 03:38:48',1,'dod_anzio',319,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429600,'2026-08-13 03:38:50',1,'dod_anzio',320,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429601,'2026-08-13 03:38:52',1,'dod_anzio',305,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429602,'2026-08-13 03:38:53',1,'dod_anzio',304,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429603,'2026-08-13 03:38:54',1,'dod_anzio',307,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429604,'2026-08-13 03:38:55',1,'dod_anzio',306,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429605,'2026-08-13 03:38:57',1,'dod_anzio',309,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429606,'2026-08-13 03:38:58',1,'dod_anzio',308,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429607,'2026-08-13 03:38:59',1,'dod_anzio',313,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429608,'2026-08-13 03:39:00',1,'dod_anzio',311,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429609,'2026-08-13 03:39:02',1,'dod_anzio',316,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429610,'2026-08-13 03:39:03',1,'dod_anzio',314,'Axis',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429611,'2026-08-13 03:39:04',1,'dod_anzio',318,'Allies',NULL);
INSERT INTO `hlstats_Events_ChangeTeam` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `team`, `match_id`) VALUES (429612,'2026-08-13 03:39:05',1,'dod_anzio',317,'Axis',NULL);
/*!40000 ALTER TABLE `hlstats_Events_ChangeTeam` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Chat`
--

DROP TABLE IF EXISTS `hlstats_Events_Chat`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Chat` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `message_mode` tinyint NOT NULL DEFAULT '0',
  `message` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`),
  KEY `serverId` (`serverId`),
  FULLTEXT KEY `message` (`message`)
) ENGINE=MyISAM AUTO_INCREMENT=257885 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Chat`
--

LOCK TABLES `hlstats_Events_Chat` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Chat` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_Chat` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Connects`
--

DROP TABLE IF EXISTS `hlstats_Events_Connects`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Connects` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `ipAddress` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `hostname` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `hostgroup` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `eventTime_Disconnect` datetime DEFAULT NULL,
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM AUTO_INCREMENT=44969 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Connects`
--

LOCK TABLES `hlstats_Events_Connects` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Connects` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_Connects` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Disconnects`
--

DROP TABLE IF EXISTS `hlstats_Events_Disconnects`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Disconnects` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=33823 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Disconnects`
--

LOCK TABLES `hlstats_Events_Disconnects` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Disconnects` DISABLE KEYS */;
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33808,'2026-08-13 03:38:36',1,'dod_anzio',304,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33809,'2026-08-13 03:38:36',1,'dod_anzio',305,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33810,'2026-08-13 03:38:36',1,'dod_anzio',306,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33811,'2026-08-13 03:38:36',1,'dod_anzio',307,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33812,'2026-08-13 03:38:36',1,'dod_anzio',308,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33813,'2026-08-13 03:38:36',1,'dod_anzio',309,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33814,'2026-08-13 03:38:36',1,'dod_anzio',310,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33815,'2026-08-13 03:38:36',1,'dod_anzio',311,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33816,'2026-08-13 03:38:36',1,'dod_anzio',312,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33817,'2026-08-13 03:38:36',1,'dod_anzio',313,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33818,'2026-08-13 03:38:36',1,'dod_anzio',314,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33819,'2026-08-13 03:38:36',1,'dod_anzio',315,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33820,'2026-08-13 03:38:36',1,'dod_anzio',316,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33821,'2026-08-13 03:38:36',1,'dod_anzio',317,NULL);
INSERT INTO `hlstats_Events_Disconnects` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `match_id`) VALUES (33822,'2026-08-13 03:38:36',1,'dod_anzio',318,NULL);
/*!40000 ALTER TABLE `hlstats_Events_Disconnects` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Entries`
--

DROP TABLE IF EXISTS `hlstats_Events_Entries`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Entries` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM AUTO_INCREMENT=400630 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Entries`
--

LOCK TABLES `hlstats_Events_Entries` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Entries` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_Entries` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Frags`
--

DROP TABLE IF EXISTS `hlstats_Events_Frags`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Frags` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `killerId` int unsigned NOT NULL DEFAULT '0',
  `victimId` int unsigned NOT NULL DEFAULT '0',
  `weapon` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `headshot` tinyint(1) NOT NULL DEFAULT '0',
  `killerRole` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `victimRole` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `pos_x` mediumint DEFAULT NULL,
  `pos_y` mediumint DEFAULT NULL,
  `pos_z` mediumint DEFAULT NULL,
  `pos_victim_x` mediumint DEFAULT NULL,
  `pos_victim_y` mediumint DEFAULT NULL,
  `pos_victim_z` mediumint DEFAULT NULL,
  `half` tinyint NOT NULL DEFAULT '0',
  `k_prone` tinyint NOT NULL DEFAULT '0',
  `v_prone` tinyint NOT NULL DEFAULT '0',
  `k_scope` tinyint NOT NULL DEFAULT '0',
  `v_scope` tinyint NOT NULL DEFAULT '0',
  `k_clip` smallint NOT NULL DEFAULT '-1',
  `k_ammo` smallint NOT NULL DEFAULT '-1',
  `v_clip` smallint NOT NULL DEFAULT '-1',
  `v_ammo` smallint NOT NULL DEFAULT '-1',
  `is_last_flag_defense` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `killerId` (`killerId`),
  KEY `victimId` (`victimId`),
  KEY `serverId` (`serverId`),
  KEY `headshot` (`headshot`),
  KEY `map` (`map`(5)),
  KEY `weapon16` (`weapon`(16)),
  KEY `killerRole` (`killerRole`(8)),
  KEY `idx_match_id` (`match_id`)
) ENGINE=MyISAM AUTO_INCREMENT=1255455 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Frags`
--

LOCK TABLES `hlstats_Events_Frags` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Frags` DISABLE KEYS */;
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255103,'2026-08-13 03:08:08',1,'dod_anzio','1786590465-TEST',318,304,'luger',0,'#class_axis_pschreck','#class_allied_carbine',353,824,-372,38,848,-390,1,0,0,0,0,3,16,7,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255104,'2026-08-13 03:08:14',1,'dod_anzio','1786590465-TEST',310,308,'mp40',0,'Random','#class_allied_heavy',184,839,-390,0,829,-390,1,0,0,0,0,27,180,0,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255105,'2026-08-13 03:08:19',1,'dod_anzio','1786590465-TEST',314,309,'30cal',0,'#class_allied_mg','#class_axis_mp44',-942,868,-422,-700,921,-422,1,0,0,0,0,138,150,27,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255106,'2026-08-13 03:08:21',1,'dod_anzio','1786590465-TEST',315,318,'garand',0,'Random','#class_axis_pschreck',-1187,634,-398,-8,652,-392,1,0,0,0,0,7,80,0,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255107,'2026-08-13 03:08:34',1,'dod_anzio','1786590465-TEST',315,313,'garand',0,'Random','#class_axis_sniper',-4,799,-390,919,846,-382,1,0,0,0,0,4,80,5,60,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255108,'2026-08-13 03:08:35',1,'dod_anzio','1786590465-TEST',315,310,'garand',0,'Random','Random',-4,799,-390,291,857,-372,1,0,0,0,0,3,80,1,1,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255109,'2026-08-13 03:08:36',1,'dod_anzio','1786590465-TEST',315,316,'garand',0,'Random','#class_axis_mg34',-4,799,-390,858,829,-390,1,0,0,0,0,1,80,75,375,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255110,'2026-08-13 03:08:46',1,'dod_anzio','1786590465-TEST',306,312,'greasegun',0,'#class_allied_grease','Random',-918,544,-382,-666,794,-409,1,0,0,0,0,25,180,1,4,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255111,'2026-08-13 03:19:46',1,'dod_anzio','1786590465-TEST',316,317,'mg34',0,'#class_axis_mg34','#class_allied_bazooka',1373,1141,-297,1418,791,-372,1,0,0,0,0,73,375,5,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255112,'2026-08-13 03:19:47',1,'dod_anzio','1786590465-TEST',315,316,'garand',0,'Random','#class_axis_mg34',1363,779,-372,1373,1141,-297,1,0,0,0,0,3,72,66,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255113,'2026-08-13 03:19:48',1,'dod_anzio','1786590465-TEST',315,305,'garand',0,'Random','#class_axis_k43',1363,779,-372,1264,943,-372,1,0,0,0,0,2,72,10,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255114,'2026-08-13 03:19:56',1,'dod_anzio','1786590465-TEST',315,307,'garand',0,'Random','#class_axis_mp40',1748,216,-372,1672,-62,-374,1,0,0,0,0,6,64,30,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255115,'2026-08-13 03:20:09',1,'dod_anzio','1786590465-TEST',306,313,'greasegun',0,'#class_allied_grease','#class_axis_sniper',202,856,-390,272,885,-372,1,0,0,0,0,21,174,4,16,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255116,'2026-08-13 03:20:19',1,'dod_anzio','1786590465-TEST',310,306,'mg34',0,'Random','#class_allied_grease',56,827,-390,152,762,-390,1,0,0,0,0,67,375,20,174,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255117,'2026-08-13 03:20:20',1,'dod_anzio','1786590465-TEST',315,305,'garand',0,'Random','#class_axis_k43',1396,805,-390,1384,1267,-270,1,0,0,0,0,5,64,6,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255118,'2026-08-13 03:20:23',1,'dod_anzio','1786590465-TEST',315,316,'grenade',0,'Random','#class_axis_mg34',1385,1256,-252,1531,1513,-252,1,12,0,0,0,4,0,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255119,'2026-08-13 03:20:26',1,'dod_anzio','1786590465-TEST',309,308,'mp44',0,'#class_axis_mp44','#class_allied_heavy',-124,125,-414,293,-106,-390,1,0,0,0,0,26,180,20,239,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255120,'2026-08-13 03:20:37',1,'dod_anzio','1786590465-TEST',310,317,'mg34',0,'Random','#class_allied_bazooka',-674,737,-422,-1156,662,-402,1,2,0,0,0,65,375,1,5,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255121,'2026-08-13 03:20:42',1,'dod_anzio','1786590465-TEST',318,311,'luger',1,'#class_axis_pschreck','#class_allied_sniper',1429,628,-372,1416,841,-372,1,0,0,0,0,7,16,4,49,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255122,'2026-08-13 03:20:48',1,'dod_anzio','1786590465-TEST',318,314,'luger',0,'#class_axis_pschreck','#class_allied_mg',1400,732,-390,1474,536,-372,1,0,0,0,0,1,16,129,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255123,'2026-08-13 03:21:03',1,'dod_anzio','1786590465-TEST',316,315,'mg34',0,'#class_axis_mg34','Random',985,823,-382,-12,798,-390,1,2,0,0,0,73,375,7,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255124,'2026-08-13 03:21:04',1,'dod_anzio','1786590465-TEST',307,308,'mp40',0,'#class_axis_mp40','#class_allied_heavy',-676,229,-407,-12,670,-410,1,0,0,0,0,19,180,20,240,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255125,'2026-08-13 03:21:14',1,'dod_anzio','1786590465-TEST',313,304,'scopedkar',0,'#class_axis_sniper','#class_allied_carbine',-24,807,-390,-104,-36,-438,1,0,0,1,0,5,59,7,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255126,'2026-08-13 03:21:17',1,'dod_anzio','1786590465-TEST',318,311,'spade',0,'#class_axis_pschreck','#class_allied_sniper',20,-147,-412,52,-164,-412,1,0,0,0,0,0,0,0,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255127,'2026-08-13 03:21:27',1,'dod_anzio','1786590465-TEST',309,306,'mp44',0,'#class_axis_mp44','#class_allied_grease',1765,-121,-374,985,-268,-332,1,0,0,0,0,21,175,24,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255128,'2026-08-13 03:21:38',1,'dod_anzio','1786590465-TEST',313,314,'scopedkar',0,'#class_axis_sniper','#class_allied_mg',-753,702,-421,-684,1104,-414,1,0,2,0,0,3,58,147,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255129,'2026-08-13 03:21:39',1,'dod_anzio','1786590465-TEST',309,315,'mp44',0,'#class_axis_mp44','Random',1672,-66,-374,648,-780,-328,1,0,0,0,0,24,165,20,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255130,'2026-08-13 03:21:44',1,'dod_anzio','1786590465-TEST',311,313,'spring',0,'#class_allied_sniper','#class_axis_sniper',-1273,-735,-372,-1228,870,-187,1,0,0,1,0,5,50,2,58,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255131,'2026-08-13 03:21:53',1,'dod_anzio','1786590465-TEST',308,316,'bar',0,'#class_allied_heavy','#class_axis_mg34',0,827,-390,763,817,-364,1,0,0,0,0,16,240,75,370,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255132,'2026-08-13 03:21:55',1,'dod_anzio','1786590465-TEST',318,311,'spade',0,'#class_axis_pschreck','#class_allied_sniper',-1272,-584,-336,-1288,-578,-390,1,0,0,0,0,0,0,7,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255133,'2026-08-13 03:22:40',1,'dod_anzio','1786590465-TEST',315,316,'30cal',0,'Random','#class_axis_mg34',472,796,-390,800,823,-382,1,2,0,0,0,149,150,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255134,'2026-08-13 03:22:42',1,'dod_anzio','1786590465-TEST',312,311,'mg34',0,'Random','#class_allied_sniper',1156,765,-364,929,-267,-339,1,0,0,0,0,65,375,4,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255135,'2026-08-13 03:22:44',1,'dod_anzio','1786590465-TEST',309,317,'mp44',0,'#class_axis_mp44','#class_allied_bazooka',246,944,-390,245,861,-390,1,0,0,0,0,29,180,7,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255136,'2026-08-13 03:22:44',1,'dod_anzio','1786590465-TEST',308,309,'bar',1,'#class_allied_heavy','#class_axis_mp44',-3,791,-390,246,944,-372,1,0,0,0,0,13,240,26,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255137,'2026-08-13 03:22:51',1,'dod_anzio','1786590465-TEST',304,307,'grenade',0,'#class_allied_carbine','#class_axis_mp40',724,772,-390,319,881,-372,1,0,0,0,0,2,1,28,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255138,'2026-08-13 03:22:54',1,'dod_anzio','1786590465-TEST',310,315,'mp40',0,'Random','Random',1022,904,-382,895,833,-382,1,0,0,0,0,23,151,132,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255139,'2026-08-13 03:22:55',1,'dod_anzio','1786590465-TEST',310,304,'mp40',0,'Random','#class_allied_carbine',1022,904,-382,742,752,-390,1,0,0,0,0,17,151,12,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255140,'2026-08-13 03:23:04',1,'dod_anzio','1786590465-TEST',308,310,'bar',0,'#class_allied_heavy','Random',754,808,-382,1000,886,-382,1,0,0,0,0,20,232,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255141,'2026-08-13 03:23:07',1,'dod_anzio','1786590465-TEST',308,312,'bar',0,'#class_allied_heavy','Random',798,822,-382,1012,900,-382,1,0,0,0,0,8,232,73,364,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255142,'2026-08-13 03:23:11',1,'dod_anzio','1786590465-TEST',308,313,'bar',0,'#class_allied_heavy','#class_axis_sniper',938,835,-382,1024,916,-382,1,0,0,0,0,6,232,8,16,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255143,'2026-08-13 03:23:18',1,'dod_anzio','1786590465-TEST',305,314,'luger',0,'#class_axis_k43','#class_allied_mg',1171,-273,-336,1056,-221,-350,1,0,0,0,0,7,16,141,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255144,'2026-08-13 03:23:21',1,'dod_anzio','1786590465-TEST',309,306,'mp44',0,'#class_axis_mp44','#class_allied_grease',-258,1159,-398,-696,924,-404,1,0,0,0,0,24,180,30,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255145,'2026-08-13 03:23:25',1,'dod_anzio','1786590465-TEST',317,305,'colt',1,'#class_allied_bazooka','#class_axis_k43',1024,-271,-350,1171,-273,-336,1,0,0,0,0,3,14,0,16,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255146,'2026-08-13 03:23:30',1,'dod_anzio','1786590465-TEST',318,317,'luger',0,'#class_axis_pschreck','#class_allied_bazooka',1257,-206,-361,1024,-271,-332,1,0,0,0,0,4,8,0,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255147,'2026-08-13 03:23:36',1,'dod_anzio','1786590465-TEST',308,318,'bar',0,'#class_allied_heavy','#class_axis_pschreck',1770,-87,-356,1147,-211,-352,1,0,0,0,0,3,212,3,8,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255148,'2026-08-13 03:23:37',1,'dod_anzio','1786590465-TEST',304,316,'m1carbine',0,'#class_allied_carbine','#class_axis_mg34',-576,621,-404,-669,918,-404,1,0,0,0,0,10,150,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255149,'2026-08-13 03:23:38',1,'dod_anzio','1786590465-TEST',304,309,'m1carbine',0,'#class_allied_carbine','#class_axis_mp44',-653,811,-384,-703,926,-404,1,0,0,0,0,4,150,1,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255150,'2026-08-13 03:23:43',1,'dod_anzio','1786590465-TEST',309,304,'grenade2',0,'#class_axis_mp44','#class_allied_carbine',2694,2256,-388,-664,795,-391,1,0,0,0,0,1,0,3,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255151,'2026-08-13 03:23:48',1,'dod_anzio','1786590465-TEST',312,308,'k43',0,'Random','#class_allied_heavy',1435,743,-372,1172,-273,-336,1,0,0,0,0,4,70,20,194,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255152,'2026-08-13 03:24:12',1,'dod_anzio','1786590465-TEST',312,314,'k43',0,'Random','#class_allied_mg',1771,-79,-356,1047,-288,-332,1,0,0,0,0,3,63,140,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255153,'2026-08-13 03:24:13',1,'dod_anzio','1786590465-TEST',310,317,'mp44',0,'Random','#class_allied_bazooka',-12,780,-390,-151,137,-413,1,0,0,0,0,26,180,1,5,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255154,'2026-08-13 03:24:15',1,'dod_anzio','1786590465-TEST',316,311,'mg34',0,'#class_axis_mg34','#class_allied_sniper',1375,-194,-372,1171,-285,-354,1,2,0,0,0,50,375,2,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255155,'2026-08-13 03:24:18',1,'dod_anzio','1786590465-TEST',310,306,'mp44',0,'Random','#class_allied_grease',-26,580,-410,-121,-52,-438,1,0,0,0,0,21,180,28,180,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255156,'2026-08-13 03:24:18',1,'dod_anzio','1786590465-TEST',315,316,'garand',0,'Random','#class_axis_mg34',548,-342,-372,1170,-272,-354,1,0,1,0,0,2,80,49,375,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255157,'2026-08-13 03:24:24',1,'dod_anzio','1786590465-TEST',312,315,'k43',0,'Random','Random',1559,-190,-356,548,-342,-372,1,0,0,0,0,6,53,5,72,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255158,'2026-08-13 03:24:24',1,'dod_anzio','1786590465-TEST',312,304,'k43',1,'Random','#class_allied_carbine',1559,-190,-356,471,-346,-372,1,0,0,0,0,5,53,0,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255159,'2026-08-13 03:24:43',1,'dod_anzio','1786590465-TEST',314,310,'30cal',1,'#class_allied_mg','Random',-1279,-793,-382,-1239,-524,-372,1,2,0,0,0,149,150,20,170,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255160,'2026-08-13 03:24:45',1,'dod_anzio','1786590465-TEST',313,317,'scopedkar',0,'#class_axis_sniper','#class_allied_bazooka',-16,-168,-412,191,-2,-395,1,0,0,0,0,5,58,6,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255161,'2026-08-13 03:24:58',1,'dod_anzio','1786590465-TEST',315,318,'bar',0,'Random','#class_axis_pschreck',-25,18,-438,-334,-229,-372,1,0,0,0,0,14,240,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255162,'2026-08-13 03:24:59',1,'dod_anzio','1786590465-TEST',313,315,'scopedkar',0,'#class_axis_sniper','Random',52,-155,-430,-24,174,-401,1,0,0,0,0,5,57,11,240,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255163,'2026-08-13 03:24:59',1,'dod_anzio','1786590465-TEST',314,313,'30cal',1,'#class_allied_mg','#class_axis_sniper',-1022,1104,-414,52,-155,-430,1,2,0,0,0,147,150,4,57,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255164,'2026-08-13 03:25:01',1,'dod_anzio','1786590465-TEST',312,311,'k43',0,'Random','#class_allied_sniper',929,847,-382,692,812,-390,1,0,0,0,0,10,47,7,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255165,'2026-08-13 03:25:12',1,'dod_anzio','1786590465-TEST',309,304,'mp44',1,'#class_axis_mp44','#class_allied_carbine',440,-326,-390,388,-252,-390,1,0,0,0,0,29,176,11,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255166,'2026-08-13 03:25:20',1,'dod_anzio','1786590465-TEST',305,306,'k43',0,'#class_axis_k43','#class_allied_grease',733,-246,-372,717,-99,-414,1,0,0,0,0,10,70,27,178,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255167,'2026-08-13 03:25:23',1,'dod_anzio','1786590465-TEST',309,317,'mp44',0,'#class_axis_mp44','#class_allied_bazooka',-225,-157,-392,-478,-393,-372,1,0,0,0,0,25,174,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255168,'2026-08-13 03:25:24',1,'dod_anzio','1786590465-TEST',307,314,'mp40',0,'#class_axis_mp40','#class_allied_mg',-662,739,-404,-673,930,-422,1,0,0,0,0,26,180,140,146,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255169,'2026-08-13 03:25:29',1,'dod_anzio','1786590465-TEST',309,308,'mp44',0,'#class_axis_mp44','#class_allied_heavy',-554,-693,-339,-506,-900,-327,1,0,0,0,0,18,174,14,240,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255170,'2026-08-13 03:25:33',1,'dod_anzio','1786590465-TEST',312,311,'k43',0,'Random','#class_allied_sniper',-20,805,-390,-37,43,-438,1,0,0,0,0,8,46,4,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255171,'2026-08-13 03:25:38',1,'dod_anzio','1786590465-TEST',306,309,'greasegun',0,'#class_allied_grease','#class_axis_mp44',-667,-1614,-536,-480,-950,-332,1,0,0,0,0,4,180,0,174,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255172,'2026-08-13 03:25:44',1,'dod_anzio','1786590465-TEST',304,312,'m1carbine',0,'#class_allied_carbine','Random',38,-155,-430,-446,613,-404,1,0,0,0,0,13,150,7,46,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255173,'2026-08-13 03:25:51',1,'dod_anzio','1786590465-TEST',315,307,'garand',0,'Random','#class_axis_mp40',-121,262,-422,-642,663,-422,1,0,0,0,0,4,80,24,175,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255174,'2026-08-13 03:25:59',1,'dod_anzio','1786590465-TEST',315,318,'garand',0,'Random','#class_axis_pschreck',0,805,-390,731,809,-382,1,0,0,0,0,3,80,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255175,'2026-08-13 03:26:01',1,'dod_anzio','1786590465-TEST',315,310,'garand',1,'Random','Random',0,805,-390,684,804,-372,1,0,0,0,0,1,80,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255176,'2026-08-13 03:26:07',1,'dod_anzio','1786590465-TEST',305,315,'k43butt',0,'#class_axis_k43','Random',18,831,-390,-8,799,-390,1,0,0,0,0,10,0,0,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255177,'2026-08-13 03:26:10',1,'dod_anzio','1786590465-TEST',305,308,'k43',0,'#class_axis_k43','#class_allied_heavy',18,831,-390,-13,584,-410,1,0,0,0,0,9,69,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255178,'2026-08-13 03:26:19',1,'dod_anzio','1786590465-TEST',304,305,'m1carbine',0,'#class_allied_carbine','#class_axis_k43',-10,664,-410,-15,805,-390,1,0,0,0,0,11,147,8,16,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255179,'2026-08-13 03:26:29',1,'dod_anzio','1786590465-TEST',311,309,'spring',0,'#class_allied_sniper','#class_axis_mp44',-983,373,-382,-604,1010,-404,1,0,0,1,0,4,50,17,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255180,'2026-08-13 03:26:30',1,'dod_anzio','1786590465-TEST',314,318,'30cal',0,'#class_allied_mg','#class_axis_pschreck',-646,647,-404,-676,964,-404,1,0,0,0,0,149,150,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255181,'2026-08-13 03:26:33',1,'dod_anzio','1786590465-TEST',314,307,'30cal',0,'#class_allied_mg','#class_axis_mp40',-657,773,-414,-767,859,-422,1,0,0,0,0,143,150,12,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255182,'2026-08-13 03:26:39',1,'dod_anzio','1786590465-TEST',312,304,'scopedkar',0,'Random','#class_allied_carbine',1288,-205,-346,838,-300,-375,1,0,0,1,0,3,60,0,142,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255183,'2026-08-13 03:26:44',1,'dod_anzio','1786590465-TEST',317,312,'colt',0,'#class_allied_bazooka','Random',1072,-156,-350,1075,-224,-326,1,0,0,0,0,7,14,3,16,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255184,'2026-08-13 03:26:46',1,'dod_anzio','1786590465-TEST',315,316,'m1carbine',0,'Random','#class_axis_mg34',-5,803,-390,904,819,-382,1,0,0,0,0,12,150,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255185,'2026-08-13 03:26:48',1,'dod_anzio','1786590465-TEST',315,313,'m1carbine',0,'Random','#class_axis_sniper',-5,803,-390,919,825,-382,1,0,0,0,0,4,150,5,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255186,'2026-08-13 03:26:58',1,'dod_anzio','1786590465-TEST',309,314,'mp44',0,'#class_axis_mp44','#class_allied_mg',603,1182,-311,30,1122,-390,1,0,2,0,0,18,180,142,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255187,'2026-08-13 03:27:03',1,'dod_anzio','1786590465-TEST',309,311,'mp44',0,'#class_axis_mp44','#class_allied_sniper',-62,1180,-390,-1127,864,-422,1,1,0,0,0,11,180,5,47,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255188,'2026-08-13 03:27:13',1,'dod_anzio','1786590465-TEST',318,308,'luger',1,'#class_axis_pschreck','#class_allied_heavy',65,1186,-372,291,866,-372,1,0,0,0,0,5,16,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255189,'2026-08-13 03:27:31',1,'dod_anzio','1786590465-TEST',317,316,'colt',0,'#class_allied_bazooka','#class_axis_mg34',1072,-156,-350,831,-248,-358,1,0,0,0,0,1,13,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255190,'2026-08-13 03:27:33',1,'dod_anzio','1786590465-TEST',311,312,'spring',0,'#class_allied_sniper','Random',383,-311,-372,918,-266,-342,1,0,0,1,0,5,50,24,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255191,'2026-08-13 03:27:44',1,'dod_anzio','1786590465-TEST',304,318,'m1carbine',0,'#class_allied_carbine','#class_axis_pschreck',754,488,-468,635,565,-502,1,0,0,0,0,9,150,4,12,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255192,'2026-08-13 03:27:46',1,'dod_anzio','1786590465-TEST',305,314,'k43',1,'#class_axis_k43','#class_allied_mg',931,847,-382,487,780,-372,1,0,0,0,0,10,70,150,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255193,'2026-08-13 03:27:52',1,'dod_anzio','1786590465-TEST',308,309,'bar',0,'#class_allied_heavy','#class_axis_mp44',-152,26,-420,-288,226,-404,1,0,0,0,0,17,240,8,159,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255194,'2026-08-13 03:27:52',1,'dod_anzio','1786590465-TEST',308,307,'bar',1,'#class_allied_heavy','#class_axis_mp40',-152,26,-420,-638,693,-404,1,0,0,0,0,16,240,3,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255195,'2026-08-13 03:27:57',1,'dod_anzio','1786590465-TEST',304,305,'m1carbine',0,'#class_allied_carbine','#class_axis_k43',76,852,-390,856,825,-390,1,0,0,0,0,1,150,9,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255196,'2026-08-13 03:28:02',1,'dod_anzio','1786590465-TEST',317,313,'colt',0,'#class_allied_bazooka','#class_axis_sniper',-674,793,-393,-1041,608,-377,1,0,0,0,0,4,6,4,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255197,'2026-08-13 03:28:10',1,'dod_anzio','1786590465-TEST',318,308,'pschreck',0,'#class_axis_pschreck','#class_allied_heavy',NULL,NULL,NULL,NULL,NULL,NULL,1,0,0,0,0,-1,-1,-1,-1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255198,'2026-08-13 03:28:14',1,'dod_anzio','1786590465-TEST',316,304,'mg34',0,'#class_axis_mg34','#class_allied_carbine',78,1537,-382,61,1319,-382,1,0,0,0,0,49,375,10,120,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255199,'2026-08-13 03:28:25',1,'dod_anzio','1786590465-TEST',312,317,'scopedkar',0,'Random','#class_allied_bazooka',-392,1155,-422,-674,793,-393,1,0,0,1,0,5,59,1,5,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255200,'2026-08-13 03:28:25',1,'dod_anzio','1786590465-TEST',315,312,'m1carbine',0,'Random','Random',-660,761,-402,-392,1155,-422,1,0,0,0,0,11,126,4,59,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255201,'2026-08-13 03:28:26',1,'dod_anzio','1786590465-TEST',315,307,'m1carbine',0,'Random','#class_axis_mp40',-660,761,-402,-557,1082,-396,1,0,0,0,0,8,126,23,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255202,'2026-08-13 03:28:35',1,'dod_anzio','1786590465-TEST',311,318,'spring',0,'#class_allied_sniper','#class_axis_pschreck',-654,729,-404,-556,1071,-396,1,0,0,0,0,5,49,1,4,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255203,'2026-08-13 03:28:44',1,'dod_anzio','1786590465-TEST',306,309,'greasegun',1,'#class_allied_grease','#class_axis_mp44',-693,912,-422,-287,1150,-422,1,0,1,0,0,29,153,27,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255204,'2026-08-13 03:28:55',1,'dod_anzio','1786590465-TEST',308,316,'bar',0,'#class_allied_heavy','#class_axis_mg34',-602,632,-422,-279,604,-392,1,0,0,0,0,13,240,48,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255205,'2026-08-13 03:28:56',1,'dod_anzio','1786590465-TEST',307,306,'mp40',0,'#class_axis_mp40','#class_allied_grease',1383,1693,-252,798,1186,-276,1,0,0,0,0,18,180,27,151,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255206,'2026-08-13 03:28:57',1,'dod_anzio','1786590465-TEST',304,305,'m1carbine',0,'#class_allied_carbine','#class_axis_k43',386,-322,-390,1172,-273,-336,1,0,0,0,0,11,150,10,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255207,'2026-08-13 03:29:00',1,'dod_anzio','1786590465-TEST',315,310,'m1carbine',0,'Random','Random',-1229,854,-198,-16,502,-410,1,0,0,0,0,10,113,9,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255208,'2026-08-13 03:29:06',1,'dod_anzio','1786590465-TEST',312,311,'mp40',0,'Random','#class_allied_sniper',177,1158,-390,-301,1218,-422,1,0,0,0,0,24,180,3,47,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255209,'2026-08-13 03:29:09',1,'dod_anzio','1786590465-TEST',312,317,'mp40',0,'Random','#class_allied_bazooka',150,833,-390,0,828,-390,1,0,0,0,0,20,180,6,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255210,'2026-08-13 03:29:11',1,'dod_anzio','1786590465-TEST',315,307,'m1carbine',0,'Random','#class_axis_mp40',-842,963,-422,81,1190,-390,1,0,0,0,0,1,113,20,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255211,'2026-08-13 03:29:19',1,'dod_anzio','1786590465-TEST',318,314,'pschreck',0,'#class_axis_pschreck','#class_allied_mg',NULL,NULL,NULL,NULL,NULL,NULL,1,0,0,0,0,-1,-1,-1,-1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255212,'2026-08-13 03:29:24',1,'dod_anzio','1786590465-TEST',312,304,'mp40',0,'Random','#class_allied_carbine',875,315,-518,1253,-127,-343,1,0,0,0,0,21,169,11,144,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255213,'2026-08-13 03:29:34',1,'dod_anzio','1786590465-TEST',312,311,'mp40',0,'Random','#class_allied_sniper',925,-266,-358,384,-318,-372,1,0,0,0,0,25,159,4,50,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255214,'2026-08-13 03:29:38',1,'dod_anzio','1786590465-TEST',315,313,'m1carbine',0,'Random','#class_axis_sniper',-835,879,-422,-277,1146,-421,1,0,0,0,0,8,98,4,60,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255215,'2026-08-13 03:29:44',1,'dod_anzio','1786590465-TEST',315,310,'m1carbine',0,'Random','Random',-620,906,-417,-274,1216,-420,1,0,0,0,0,3,98,2,2,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255216,'2026-08-13 03:29:49',1,'dod_anzio','1786590465-TEST',310,315,'grenade2',0,'Random','Random',1503,669,-357,-348,1188,-422,1,0,0,0,0,2,0,2,98,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255217,'2026-08-13 03:29:50',1,'dod_anzio','1786590465-TEST',309,308,'mp44',0,'#class_axis_mp44','#class_allied_heavy',1158,-290,-335,412,-331,-372,1,0,0,0,0,24,180,14,232,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255218,'2026-08-13 03:29:57',1,'dod_anzio','1786590465-TEST',307,306,'mp40',0,'#class_axis_mp40','#class_allied_grease',1285,1533,-252,1027,1358,-260,1,0,0,0,0,26,180,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255219,'2026-08-13 03:30:03',1,'dod_anzio','1786590465-TEST',306,318,'grenade',0,'#class_allied_grease','#class_axis_pschreck',-57,-2536,-588,1211,1623,-252,1,0,0,0,0,30,180,8,8,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255220,'2026-08-13 03:30:23',1,'dod_anzio','1786590465-TEST',310,314,'mp44',0,'Random','#class_allied_mg',193,1137,-390,163,1060,-372,1,0,0,0,0,29,180,150,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255221,'2026-08-13 03:30:27',1,'dod_anzio','1786590465-TEST',315,305,'spring',0,'Random','#class_axis_k43',-176,-103,-420,291,-22,-390,1,0,0,1,0,5,50,9,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255222,'2026-08-13 03:30:28',1,'dod_anzio','1786590465-TEST',312,304,'mp40',0,'Random','#class_allied_carbine',646,782,-372,-9,848,-390,1,0,0,0,0,11,153,2,2,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255223,'2026-08-13 03:30:33',1,'dod_anzio','1786590465-TEST',304,309,'grenade',0,'#class_allied_carbine','#class_axis_mp44',-9,673,-410,81,839,-372,1,0,0,0,0,2,0,30,173,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255224,'2026-08-13 03:30:37',1,'dod_anzio','1786590465-TEST',308,312,'bar',0,'#class_allied_heavy','Random',24,837,-390,567,743,-372,1,0,0,0,0,13,240,1,1,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255225,'2026-08-13 03:30:38',1,'dod_anzio','1786590465-TEST',315,307,'spring',0,'Random','#class_axis_mp40',-7,805,-390,927,846,-382,1,0,0,1,0,5,49,30,175,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255226,'2026-08-13 03:30:50',1,'dod_anzio','1786590465-TEST',308,318,'bar',0,'#class_allied_heavy','#class_axis_pschreck',137,1476,-364,757,1541,-224,1,0,0,0,0,13,232,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255227,'2026-08-13 03:30:52',1,'dod_anzio','1786590465-TEST',315,316,'spring',1,'Random','#class_axis_mg34',-733,1094,-414,859,1223,-285,1,1,2,1,0,5,48,68,375,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255228,'2026-08-13 03:31:02',1,'dod_anzio','1786590465-TEST',315,310,'spring',0,'Random','Random',-733,1094,-414,569,1174,-317,1,1,0,1,0,5,47,2,2,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255229,'2026-08-13 03:31:03',1,'dod_anzio','1786590465-TEST',307,308,'mp40',0,'#class_axis_mp40','#class_allied_heavy',472,1897,-382,137,1476,-364,1,0,0,0,0,16,180,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255230,'2026-08-13 03:31:07',1,'dod_anzio','1786590465-TEST',305,315,'k43',0,'#class_axis_k43','Random',924,1239,-264,-733,1094,-414,1,0,1,0,0,4,70,3,47,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255231,'2026-08-13 03:31:08',1,'dod_anzio','1786590465-TEST',308,307,'grenade',0,'#class_allied_heavy','#class_axis_mp40',-411,1183,-422,29,1504,-356,1,0,0,0,0,1,0,15,180,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255232,'2026-08-13 03:31:09',1,'dod_anzio','1786590465-TEST',309,311,'mp44',0,'#class_axis_mp44','#class_allied_sniper',683,1169,-296,-411,1183,-422,1,0,0,0,0,20,180,2,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255233,'2026-08-13 03:31:14',1,'dod_anzio','1786590465-TEST',309,317,'mp44',0,'#class_axis_mp44','#class_allied_bazooka',-13,1184,-372,-1161,857,-422,1,0,0,0,0,16,180,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255234,'2026-08-13 03:31:24',1,'dod_anzio','1786590465-TEST',309,314,'mp44',0,'#class_axis_mp44','#class_allied_mg',-685,904,-404,-1124,746,-415,1,0,2,0,0,27,165,150,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255235,'2026-08-13 03:32:23',1,'dod_anzio','1786590465-TEST',313,306,'scopedkar',1,'#class_axis_sniper','#class_allied_grease',-138,1170,-372,-924,873,-422,1,0,0,1,0,5,60,20,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255236,'2026-08-13 03:32:23',1,'dod_anzio','1786590465-TEST',308,316,'bar',0,'#class_allied_heavy','#class_axis_mg34',210,822,-390,889,835,-382,1,1,0,0,0,16,240,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255237,'2026-08-13 03:32:30',1,'dod_anzio','1786590465-TEST',305,311,'k43',0,'#class_axis_k43','#class_allied_sniper',-391,1157,-422,-661,767,-400,1,0,0,0,0,10,70,3,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255238,'2026-08-13 03:32:42',1,'dod_anzio','1786590465-TEST',317,305,'colt',0,'#class_allied_bazooka','#class_axis_k43',-1192,582,-372,-1018,677,-405,1,0,0,0,0,6,14,9,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255239,'2026-08-13 03:32:42',1,'dod_anzio','1786590465-TEST',312,317,'scopedkar',0,'Random','#class_allied_bazooka',-514,971,-422,-1192,582,-372,1,0,0,1,0,5,60,5,14,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255240,'2026-08-13 03:32:43',1,'dod_anzio','1786590465-TEST',307,304,'mp40',0,'#class_axis_mp40','#class_allied_carbine',1662,-160,-374,1712,-261,-366,1,0,0,0,0,26,180,0,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255241,'2026-08-13 03:32:46',1,'dod_anzio','1786590465-TEST',307,314,'mp40',0,'#class_axis_mp40','#class_allied_mg',1705,-167,-374,1044,-281,-332,1,0,0,0,0,14,180,150,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255242,'2026-08-13 03:33:22',1,'dod_anzio','1786590465-TEST',317,313,'bazooka',0,'#class_allied_bazooka','#class_axis_sniper',NULL,NULL,NULL,NULL,NULL,NULL,1,0,0,0,0,-1,-1,-1,-1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255243,'2026-08-13 03:33:24',1,'dod_anzio','1786590465-TEST',311,309,'spring',0,'#class_allied_sniper','#class_axis_mp44',816,-205,-361,1363,790,-372,1,0,0,1,0,4,49,30,180,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255244,'2026-08-13 03:33:28',1,'dod_anzio','1786590465-TEST',305,317,'k43',0,'#class_axis_k43','#class_allied_bazooka',-248,1381,-276,-671,769,-402,1,0,0,0,0,8,70,1,4,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255245,'2026-08-13 03:33:36',1,'dod_anzio','1786590465-TEST',314,316,'30cal',0,'#class_allied_mg','#class_axis_mg34',78,826,-390,875,833,-382,1,2,0,0,0,146,150,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255246,'2026-08-13 03:33:39',1,'dod_anzio','1786590465-TEST',312,314,'scopedkar',0,'Random','#class_allied_mg',211,976,-372,476,786,-372,1,0,0,0,0,5,59,145,150,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255247,'2026-08-13 03:33:45',1,'dod_anzio','1786590465-TEST',304,305,'m1carbine',0,'#class_allied_carbine','#class_axis_k43',-663,768,-401,-298,1340,-230,1,0,0,0,0,13,150,10,67,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255248,'2026-08-13 03:33:53',1,'dod_anzio','1786590465-TEST',308,307,'bar',0,'#class_allied_heavy','#class_axis_mp40',1269,940,-390,1453,677,-372,1,0,0,0,0,15,236,24,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255249,'2026-08-13 03:34:01',1,'dod_anzio','1786590465-TEST',312,304,'luger',0,'Random','#class_allied_carbine',-574,619,-422,-594,741,-411,1,0,0,0,0,6,16,10,147,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255250,'2026-08-13 03:34:03',1,'dod_anzio','1786590465-TEST',317,312,'bazooka',0,'#class_allied_bazooka','Random',NULL,NULL,NULL,NULL,NULL,NULL,1,0,0,0,0,-1,-1,-1,-1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255251,'2026-08-13 03:34:04',1,'dod_anzio','1786590465-TEST',313,308,'scopedkar',0,'#class_axis_sniper','#class_allied_heavy',1444,1280,-270,1359,887,-372,1,0,0,0,0,5,56,20,230,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255252,'2026-08-13 03:34:17',1,'dod_anzio','1786590465-TEST',316,311,'mg34',0,'#class_axis_mg34','#class_allied_sniper',1340,915,-390,1488,753,-381,1,2,0,0,0,68,375,3,44,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255253,'2026-08-13 03:34:28',1,'dod_anzio','1786590465-TEST',305,315,'k43',0,'#class_axis_k43','Random',-168,1133,-372,-1072,915,-422,1,0,0,0,0,10,70,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255254,'2026-08-13 03:34:32',1,'dod_anzio','1786590465-TEST',305,317,'k43',0,'#class_axis_k43','#class_allied_bazooka',-440,1158,-422,-685,892,-404,1,0,0,0,0,8,70,1,4,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255255,'2026-08-13 03:34:48',1,'dod_anzio','1786590465-TEST',305,314,'k43',0,'#class_axis_k43','#class_allied_mg',-691,887,-422,-578,622,-422,1,0,0,0,0,9,67,145,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255256,'2026-08-13 03:34:56',1,'dod_anzio','1786590465-TEST',309,306,'mp44',0,'#class_axis_mp44','#class_allied_grease',1771,-80,-374,1136,-290,-350,1,0,0,0,0,27,180,28,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255257,'2026-08-13 03:34:57',1,'dod_anzio','1786590465-TEST',309,304,'mp44',0,'#class_axis_mp44','#class_allied_carbine',1771,-80,-374,1046,-294,-332,1,0,0,0,0,23,180,2,2,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255258,'2026-08-13 03:34:58',1,'dod_anzio','1786590465-TEST',311,313,'spring',0,'#class_allied_sniper','#class_axis_sniper',-1142,408,-364,-665,766,-402,1,0,0,1,0,4,50,5,55,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255259,'2026-08-13 03:35:00',1,'dod_anzio','1786590465-TEST',307,311,'mp40',0,'#class_axis_mp40','#class_allied_sniper',-544,846,-397,-1142,408,-364,1,0,0,0,0,12,173,3,50,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255260,'2026-08-13 03:35:02',1,'dod_anzio','1786590465-TEST',304,309,'grenade',0,'#class_allied_carbine','#class_axis_mp44',-648,-2329,-588,1322,-205,-349,1,0,0,0,0,15,150,22,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255261,'2026-08-13 03:35:12',1,'dod_anzio','1786590465-TEST',310,315,'luger',0,'Random','Random',-658,773,-414,-925,658,-384,1,0,0,0,0,6,10,0,150,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255262,'2026-08-13 03:35:20',1,'dod_anzio','1786590465-TEST',314,305,'30cal',0,'#class_allied_mg','#class_axis_k43',14,-13,-438,-660,581,-422,1,2,0,0,0,150,150,4,65,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255263,'2026-08-13 03:35:21',1,'dod_anzio','1786590465-TEST',316,306,'mg34',0,'#class_axis_mg34','#class_allied_grease',-1190,621,-396,-1265,-334,-372,1,2,0,0,0,60,375,1,1,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255264,'2026-08-13 03:35:28',1,'dod_anzio','1786590465-TEST',317,312,'colt',0,'#class_allied_bazooka','Random',1358,-103,-352,1327,367,-364,1,0,0,0,0,2,7,164,250,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255265,'2026-08-13 03:35:42',1,'dod_anzio','1786590465-TEST',309,308,'mp44',0,'#class_axis_mp44','#class_allied_heavy',157,1092,-372,-162,1145,-390,1,0,1,0,0,28,180,14,240,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255266,'2026-08-13 03:35:44',1,'dod_anzio','1786590465-TEST',313,317,'scopedkar',0,'#class_axis_sniper','#class_allied_bazooka',1454,1487,-270,1358,-103,-352,1,0,0,1,0,1,60,0,4,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255267,'2026-08-13 03:35:50',1,'dod_anzio','1786590465-TEST',314,307,'30cal',0,'#class_allied_mg','#class_axis_mp40',1020,-292,-332,952,-232,-332,1,0,0,0,0,132,150,1,1,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255268,'2026-08-13 03:35:52',1,'dod_anzio','1786590465-TEST',311,310,'spring',0,'#class_allied_sniper','Random',-152,113,-434,-1008,949,-404,1,0,0,1,0,4,50,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255269,'2026-08-13 03:35:55',1,'dod_anzio','1786590465-TEST',304,316,'m1carbine',0,'#class_allied_carbine','#class_axis_mg34',-1326,-469,-390,-1756,-68,-361,1,0,0,0,0,11,150,59,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255270,'2026-08-13 03:35:55',1,'dod_anzio','1786590465-TEST',309,311,'grenade2',0,'#class_axis_mp44','#class_allied_sniper',69,699,-420,-14,579,-392,1,0,0,0,0,27,180,3,50,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255271,'2026-08-13 03:36:15',1,'dod_anzio','1786590465-TEST',312,315,'k43',0,'Random','Random',9,808,-390,-10,614,-410,1,0,0,0,0,9,70,2,2,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255272,'2026-08-13 03:36:20',1,'dod_anzio','1786590465-TEST',315,312,'grenade',0,'Random','Random',-622,756,-396,-15,647,-392,1,0,0,0,0,2,0,7,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255273,'2026-08-13 03:36:30',1,'dod_anzio','1786590465-TEST',310,304,'mp44',1,'Random','#class_allied_carbine',804,1184,-275,-73,1184,-372,1,0,0,0,0,30,180,2,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255274,'2026-08-13 03:36:35',1,'dod_anzio','1786590465-TEST',304,310,'grenade',0,'#class_allied_carbine','Random',261,-27,-381,-49,1182,-372,1,0,0,0,0,2,0,29,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255275,'2026-08-13 03:36:54',1,'dod_anzio','1786590465-TEST',306,312,'greasegun',1,'#class_allied_grease','Random',1256,-124,-343,1547,752,-312,1,0,2,0,0,30,169,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255276,'2026-08-13 03:37:00',1,'dod_anzio','1786590465-TEST',308,307,'bar',0,'#class_allied_heavy','#class_axis_mp40',-1218,562,-372,-700,922,-404,1,0,0,0,0,16,220,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255277,'2026-08-13 03:37:03',1,'dod_anzio','1786590465-TEST',317,316,'bazooka',0,'#class_allied_bazooka','#class_axis_mg34',NULL,NULL,NULL,NULL,NULL,NULL,1,0,0,0,0,-1,-1,-1,-1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255278,'2026-08-13 03:37:05',1,'dod_anzio','1786590465-TEST',307,308,'grenade2',0,'#class_axis_mp40','#class_allied_heavy',878,273,-518,-868,875,-404,1,0,0,0,0,1,0,15,220,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255279,'2026-08-13 03:37:09',1,'dod_anzio','1786590465-TEST',305,317,'k43',0,'#class_axis_k43','#class_allied_bazooka',411,801,-372,191,1014,-390,1,0,0,0,0,5,66,5,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255280,'2026-08-13 03:37:13',1,'dod_anzio','1786590465-TEST',311,310,'spring',0,'#class_allied_sniper','Random',1135,-294,-332,1506,749,-369,1,0,1,1,0,5,50,0,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255281,'2026-08-13 03:37:29',1,'dod_anzio','1786590465-TEST',306,312,'greasegun',0,'#class_allied_grease','Random',1256,-124,-343,1537,2054,-261,1,0,0,0,0,8,148,1,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255282,'2026-08-13 03:37:35',1,'dod_anzio','1786590465-TEST',306,316,'greasegun',1,'#class_allied_grease','#class_axis_mg34',1256,-124,-343,1387,1041,-354,1,0,2,0,0,6,148,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255283,'2026-08-13 03:37:44',1,'dod_anzio','1786590465-TEST',314,305,'30cal',0,'#class_allied_mg','#class_axis_k43',-1010,510,-364,-725,929,-404,1,0,0,0,0,137,150,3,66,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255284,'2026-08-13 03:37:45',1,'dod_anzio','1786590465-TEST',307,314,'mp40',0,'#class_axis_mp40','#class_allied_mg',-460,1153,-404,-1010,510,-364,1,0,0,0,0,8,180,136,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255285,'2026-08-13 03:37:51',1,'dod_anzio','1786590465-TEST',304,307,'m1carbine',0,'#class_allied_carbine','#class_axis_mp40',-586,590,-422,-592,671,-422,1,0,0,0,0,11,150,0,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255286,'2026-08-13 03:38:02',1,'dod_anzio','1786590465-TEST',312,306,'mp40',0,'Random','#class_allied_grease',1613,750,-267,1439,612,-372,1,0,0,0,0,29,180,30,123,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255287,'2026-08-13 03:38:03',1,'dod_anzio','1786590465-TEST',311,312,'spring',0,'#class_allied_sniper','Random',806,-207,-363,1577,750,-277,1,0,0,1,0,5,48,28,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255288,'2026-08-13 03:38:11',1,'dod_anzio','1786590465-TEST',315,310,'garand',0,'Random','Random',306,1147,-382,118,1457,-382,1,0,0,0,0,6,80,4,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255289,'2026-08-13 03:38:16',1,'dod_anzio','1786590465-TEST',315,305,'garand',1,'Random','#class_axis_k43',968,1290,-263,1307,1539,-252,1,0,0,0,0,4,80,9,70,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255290,'2026-08-13 03:38:22',1,'dod_anzio','1786590465-TEST',316,315,'mg34',0,'#class_axis_mg34','Random',1731,2016,-270,1085,1473,-258,1,2,0,0,0,68,375,0,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255291,'2026-08-13 03:38:23',1,'dod_anzio','1786590465-TEST',307,311,'mp40',0,'#class_axis_mp40','#class_allied_sniper',1448,596,-372,968,-175,-323,1,0,0,0,0,2,180,3,47,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255292,'2026-08-13 03:38:35',1,'dod_anzio','1786590465-TEST',307,314,'mp40',0,'#class_axis_mp40','#class_allied_mg',1242,-236,-342,858,-288,-353,1,0,0,0,0,13,151,150,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255293,'2026-08-13 03:39:33',1,'dod_anzio','1786590465-TEST',320,309,'mp44',0,'Random','#class_allied_heavy',514,807,-390,-3,799,-390,2,0,0,0,0,19,180,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255294,'2026-08-13 03:39:36',1,'dod_anzio','1786590465-TEST',313,308,'spring',0,'#class_allied_sniper','#class_axis_mp44',-1022,524,-364,-392,1155,-404,2,0,0,1,0,5,50,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255295,'2026-08-13 03:39:38',1,'dod_anzio','1786590465-TEST',309,320,'grenade',0,'#class_allied_heavy','Random',717,-35,-444,17,808,-390,2,0,0,0,0,1,0,18,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255296,'2026-08-13 03:39:38',1,'dod_anzio','1786590465-TEST',309,304,'grenade',0,'#class_allied_heavy','#class_axis_kar98',717,-35,-444,-11,728,-384,2,0,0,0,0,1,0,2,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255297,'2026-08-13 03:39:41',1,'dod_anzio','1786590465-TEST',319,306,'30cal',0,'Random','#class_axis_mp40',-1160,572,-390,-321,1154,-404,2,2,0,0,0,149,150,0,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255298,'2026-08-13 03:39:54',1,'dod_anzio','1786590465-TEST',311,313,'scopedkar',1,'#class_axis_sniper','#class_allied_sniper',-248,1552,-276,-1022,524,-364,2,0,0,1,0,5,55,0,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255299,'2026-08-13 03:40:12',1,'dod_anzio','1786590465-TEST',317,305,'spade',0,'#class_axis_pschreck','#class_allied_garand',1087,-260,-332,1064,-227,-350,2,0,0,0,0,0,0,8,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255300,'2026-08-13 03:40:14',1,'dod_anzio','1786590465-TEST',311,319,'scopedkar',1,'#class_axis_sniper','Random',-248,1552,-276,-697,915,-404,2,0,0,1,0,5,50,143,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255301,'2026-08-13 03:40:15',1,'dod_anzio','1786590465-TEST',318,306,'colt',1,'#class_allied_bazooka','#class_axis_mp40',237,1180,-372,498,1183,-330,2,0,0,0,0,5,14,19,180,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255302,'2026-08-13 03:40:20',1,'dod_anzio','1786590465-TEST',308,318,'mp44',0,'#class_axis_mp44','#class_allied_bazooka',161,1071,-372,666,1182,-317,2,0,0,0,0,18,180,0,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255303,'2026-08-13 03:40:31',1,'dod_anzio','1786590465-TEST',308,307,'mp44',0,'#class_axis_mp44','#class_allied_grease',176,1072,-372,236,861,-372,2,0,0,0,0,29,167,30,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255304,'2026-08-13 03:40:33',1,'dod_anzio','1786590465-TEST',320,313,'mp40',0,'Random','#class_allied_sniper',1228,-236,-359,394,-316,-390,2,0,1,0,0,25,180,4,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255305,'2026-08-13 03:40:41',1,'dod_anzio','1786590465-TEST',314,316,'mg34',1,'#class_axis_mg34','#class_allied_mg',-501,1511,-422,-568,1038,-422,2,2,2,0,0,75,373,135,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255306,'2026-08-13 03:41:04',1,'dod_anzio','1786590465-TEST',306,305,'mp40',0,'#class_axis_mp40','#class_allied_garand',1448,1288,-270,1045,-281,-332,2,0,0,0,0,3,180,5,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255307,'2026-08-13 03:41:15',1,'dod_anzio','1786590465-TEST',304,319,'kar',0,'#class_axis_kar98','Random',1260,-219,-362,555,-354,-372,2,0,0,0,0,5,59,7,80,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255308,'2026-08-13 03:41:16',1,'dod_anzio','1786590465-TEST',316,308,'30cal',0,'#class_allied_mg','#class_axis_mp44',-12,669,-410,4,823,-390,2,0,0,0,0,144,150,1,1,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255309,'2026-08-13 03:41:21',1,'dod_anzio','1786590465-TEST',320,316,'spade',0,'Random','#class_allied_mg',22,814,-390,0,776,-392,2,0,0,0,0,0,0,0,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255310,'2026-08-13 03:41:23',1,'dod_anzio','1786590465-TEST',313,320,'colt',0,'#class_allied_sniper','Random',-13,729,-400,18,808,-390,2,0,0,0,0,2,14,0,0,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255311,'2026-08-13 03:41:55',1,'dod_anzio','1786590465-TEST',309,306,'bar',0,'#class_allied_heavy','#class_axis_mp40',-98,-3,-438,-588,677,-422,2,1,0,0,0,18,240,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255312,'2026-08-13 03:41:57',1,'dod_anzio','1786590465-TEST',309,311,'bar',0,'#class_allied_heavy','#class_axis_sniper',-134,94,-436,-962,859,-404,2,0,0,0,0,14,240,5,48,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255313,'2026-08-13 03:41:57',1,'dod_anzio','1786590465-TEST',316,314,'30cal',0,'#class_allied_mg','#class_axis_mg34',-1021,518,-364,-930,852,-404,2,0,0,0,0,146,150,68,373,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255314,'2026-08-13 03:41:58',1,'dod_anzio','1786590465-TEST',316,317,'30cal',0,'#class_allied_mg','#class_axis_pschreck',-1021,518,-364,-355,1155,-404,2,0,0,0,0,144,150,0,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255315,'2026-08-13 03:42:02',1,'dod_anzio','1786590465-TEST',304,313,'spade',1,'#class_axis_kar98','#class_allied_sniper',7,808,-390,0,763,-395,2,0,0,0,0,0,0,0,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255316,'2026-08-13 03:42:02',1,'dod_anzio','1786590465-TEST',307,304,'greasegun',0,'#class_allied_grease','#class_axis_kar98',-15,695,-406,7,808,-390,2,0,0,0,0,17,178,0,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255317,'2026-08-13 03:42:03',1,'dod_anzio','1786590465-TEST',316,320,'30cal',0,'#class_allied_mg','Random',-1021,518,-364,-343,1153,-404,2,0,0,0,0,135,150,4,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255318,'2026-08-13 03:42:10',1,'dod_anzio','1786590465-TEST',308,307,'mp44',0,'#class_axis_mp44','#class_allied_grease',43,1218,-390,266,883,-390,2,0,0,0,0,25,180,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255319,'2026-08-13 03:42:18',1,'dod_anzio','1786590465-TEST',316,308,'30cal',1,'#class_allied_mg','#class_axis_mp44',-1021,518,-364,-378,1154,-404,2,0,0,0,0,136,134,0,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255320,'2026-08-13 03:42:35',1,'dod_anzio','1786590465-TEST',305,311,'garand',0,'#class_allied_garand','#class_axis_sniper',1044,-281,-332,1676,519,-260,2,0,0,0,0,6,80,2,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255321,'2026-08-13 03:42:38',1,'dod_anzio','1786590465-TEST',314,305,'mg34',0,'#class_axis_mg34','#class_allied_garand',1767,-133,-374,1044,-281,-350,2,2,0,0,0,72,375,3,80,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255322,'2026-08-13 03:42:43',1,'dod_anzio','1786590465-TEST',309,317,'bar',0,'#class_allied_heavy','#class_axis_pschreck',-541,1071,-404,-289,1360,-264,2,0,0,0,0,1,230,1,16,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255323,'2026-08-13 03:42:45',1,'dod_anzio','1786590465-TEST',313,314,'spring',0,'#class_allied_sniper','#class_axis_mg34',540,-346,-372,838,-290,-357,2,0,0,1,0,3,50,65,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255324,'2026-08-13 03:42:56',1,'dod_anzio','1786590465-TEST',304,313,'kar',0,'#class_axis_kar98','#class_allied_sniper',1474,1361,-270,1017,-234,-350,2,0,0,0,0,3,60,0,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255325,'2026-08-13 03:43:02',1,'dod_anzio','1786590465-TEST',308,309,'mp44',0,'#class_axis_mp44','#class_allied_heavy',285,876,-372,916,837,-364,2,0,0,0,0,23,180,20,210,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255326,'2026-08-13 03:43:07',1,'dod_anzio','1786590465-TEST',320,307,'mg34',0,'Random','#class_allied_grease',-557,564,-404,-578,741,-408,2,0,0,0,0,69,375,22,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255327,'2026-08-13 03:43:21',1,'dod_anzio','1786590465-TEST',316,320,'30cal',0,'#class_allied_mg','Random',-163,157,-428,-658,768,-416,2,2,2,0,0,116,134,68,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255328,'2026-08-13 03:43:40',1,'dod_anzio','1786590465-TEST',304,305,'kar',0,'#class_axis_kar98','#class_allied_garand',730,-226,-390,1045,-281,-332,2,0,0,0,0,3,57,2,2,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255329,'2026-08-13 03:43:42',1,'dod_anzio','1786590465-TEST',311,313,'scopedkar',0,'#class_axis_sniper','#class_allied_sniper',-248,1542,-276,-1244,295,-372,2,0,0,1,0,4,60,4,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255330,'2026-08-13 03:43:46',1,'dod_anzio','1786590465-TEST',309,317,'bar',0,'#class_allied_heavy','#class_axis_pschreck',-625,654,-404,-565,1345,-396,2,0,0,0,0,16,240,0,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255331,'2026-08-13 03:43:57',1,'dod_anzio','1786590465-TEST',309,308,'bar',1,'#class_allied_heavy','#class_axis_mp44',-652,713,-422,-320,322,-422,2,0,1,0,0,17,235,13,172,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255332,'2026-08-13 03:44:09',1,'dod_anzio','1786590465-TEST',319,320,'garand',0,'Random','Random',-395,1168,-422,-273,1347,-258,2,0,0,0,0,7,80,2,2,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255333,'2026-08-13 03:44:12',1,'dod_anzio','1786590465-TEST',319,311,'garand',0,'Random','#class_axis_sniper',-355,1193,-422,-265,1354,-264,2,0,0,0,0,3,80,4,58,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255334,'2026-08-13 03:44:14',1,'dod_anzio','1786590465-TEST',319,306,'garand',0,'Random','#class_axis_mp40',-355,1193,-422,160,1075,-372,2,0,0,0,0,1,80,20,180,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255335,'2026-08-13 03:44:19',1,'dod_anzio','1786590465-TEST',319,317,'garand',0,'Random','#class_axis_pschreck',-289,1216,-422,918,1228,-265,2,0,0,0,0,8,72,1,5,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255336,'2026-08-13 03:44:26',1,'dod_anzio','1786590465-TEST',319,314,'garand',0,'Random','#class_axis_mg34',-289,1216,-422,-975,859,-404,2,0,0,0,0,5,72,72,375,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255337,'2026-08-13 03:44:34',1,'dod_anzio','1786590465-TEST',308,313,'mp44',0,'#class_axis_mp44','#class_allied_sniper',-337,1355,-422,-855,786,-402,2,0,0,0,0,24,180,5,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255338,'2026-08-13 03:44:36',1,'dod_anzio','1786590465-TEST',319,308,'colt',0,'Random','#class_axis_mp44',-289,1216,-422,-337,1355,-422,2,0,0,0,0,2,14,23,180,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255339,'2026-08-13 03:44:45',1,'dod_anzio','1786590465-TEST',320,319,'k43',0,'Random','Random',523,1164,-325,-289,1216,-422,2,0,0,0,0,9,70,2,2,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255340,'2026-08-13 03:44:46',1,'dod_anzio','1786590465-TEST',307,304,'greasegun',0,'#class_allied_grease','#class_axis_kar98',1042,-286,-332,396,-308,-372,2,0,0,0,0,13,180,4,54,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255341,'2026-08-13 03:45:02',1,'dod_anzio','1786590465-TEST',320,316,'k43',0,'Random','#class_allied_mg',-434,921,-404,-918,871,-404,2,0,0,0,0,8,68,109,134,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255342,'2026-08-13 03:45:16',1,'dod_anzio','1786590465-TEST',314,307,'mg34',0,'#class_axis_mg34','#class_allied_grease',1400,779,-390,1365,-106,-353,2,2,0,0,0,71,375,22,162,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255343,'2026-08-13 03:45:17',1,'dod_anzio','1786590465-TEST',311,313,'scopedkar',0,'#class_axis_sniper','#class_allied_sniper',-684,934,-422,-1132,442,-364,2,0,0,1,0,5,60,5,50,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255344,'2026-08-13 03:45:18',1,'dod_anzio','1786590465-TEST',309,314,'bar',0,'#class_allied_heavy','#class_axis_mg34',1067,-227,-332,1272,611,-364,2,0,0,0,0,18,231,69,375,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255345,'2026-08-13 03:45:26',1,'dod_anzio','1786590465-TEST',309,304,'bar',0,'#class_allied_heavy','#class_axis_kar98',985,-274,-332,1770,-198,-356,2,0,0,0,0,8,231,2,2,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255346,'2026-08-13 03:45:35',1,'dod_anzio','1786590465-TEST',308,319,'mp44',0,'#class_axis_mp44','Random',-505,1278,-422,-669,793,-409,2,1,0,0,0,25,180,6,80,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255347,'2026-08-13 03:45:41',1,'dod_anzio','1786590465-TEST',305,317,'garand',0,'#class_allied_garand','#class_axis_pschreck',-796,-844,-364,-1254,-812,-364,2,0,0,0,0,3,80,0,16,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255348,'2026-08-13 03:45:48',1,'dod_anzio','1786590465-TEST',306,309,'mp40',0,'#class_axis_mp40','#class_allied_heavy',875,317,-518,913,-186,-343,2,0,0,0,0,9,180,17,218,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255349,'2026-08-13 03:45:52',1,'dod_anzio','1786590465-TEST',313,311,'spring',0,'#class_allied_sniper','#class_axis_sniper',-1179,390,-372,-1192,857,-308,2,0,0,1,0,5,50,5,59,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255350,'2026-08-13 03:46:38',1,'dod_anzio','1786590465-TEST',309,314,'bar',0,'#class_allied_heavy','#class_axis_mg34',245,-19,-384,406,-153,-390,2,0,0,0,0,14,240,54,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255351,'2026-08-13 03:46:41',1,'dod_anzio','1786590465-TEST',320,313,'k43',0,'Random','#class_allied_sniper',-1256,218,-372,-1002,659,-384,2,0,0,0,0,7,60,2,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255352,'2026-08-13 03:46:42',1,'dod_anzio','1786590465-TEST',306,316,'mp40',0,'#class_axis_mp40','#class_allied_mg',-1124,717,-393,-374,1189,-404,2,0,0,0,0,9,158,150,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255353,'2026-08-13 03:46:50',1,'dod_anzio','1786590465-TEST',307,317,'greasegun',1,'#class_allied_grease','#class_axis_pschreck',107,1368,-382,480,1342,-382,2,0,0,0,0,18,178,4,16,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255354,'2026-08-13 03:46:59',1,'dod_anzio','1786590465-TEST',309,304,'bar',0,'#class_allied_heavy','#class_axis_kar98',1046,-278,-332,913,-912,-500,2,0,0,0,0,4,233,3,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255355,'2026-08-13 03:47:04',1,'dod_anzio','1786590465-TEST',307,314,'greasegun',0,'#class_allied_grease','#class_axis_mg34',1186,1433,-254,1500,1862,-252,2,0,0,0,0,22,165,75,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255356,'2026-08-13 03:47:16',1,'dod_anzio','1786590465-TEST',307,317,'greasegun',1,'#class_allied_grease','#class_axis_pschreck',1186,1433,-254,1539,2119,-294,2,0,0,0,0,21,165,0,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255357,'2026-08-13 03:47:16',1,'dod_anzio','1786590465-TEST',320,319,'k43',0,'Random','Random',-627,771,-408,-1174,690,-406,2,0,0,0,0,9,56,5,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255358,'2026-08-13 03:47:30',1,'dod_anzio','1786590465-TEST',320,307,'k43',0,'Random','#class_allied_grease',-452,1149,-422,675,1149,-298,2,0,0,0,0,8,54,30,155,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255359,'2026-08-13 03:47:31',1,'dod_anzio','1786590465-TEST',304,316,'kar',0,'#class_axis_kar98','#class_allied_mg',1488,489,-372,1041,-167,-332,2,0,0,0,0,4,60,132,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255360,'2026-08-13 03:47:34',1,'dod_anzio','1786590465-TEST',304,309,'bayonet',0,'#class_axis_kar98','#class_allied_heavy',1731,184,-372,1763,206,-372,2,0,0,0,0,3,60,0,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255361,'2026-08-13 03:47:46',1,'dod_anzio','1786590465-TEST',313,306,'spring',0,'#class_allied_sniper','#class_axis_mp40',-1187,641,-399,-568,732,-409,2,0,0,1,0,5,50,30,130,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255362,'2026-08-13 03:48:11',1,'dod_anzio','1786590465-TEST',309,311,'bar',0,'#class_allied_heavy','#class_axis_sniper',0,800,-390,172,876,-372,2,0,0,0,0,18,240,5,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255363,'2026-08-13 03:48:12',1,'dod_anzio','1786590465-TEST',304,313,'kar',0,'#class_axis_kar98','#class_allied_sniper',94,-39,-415,-382,380,-404,2,0,0,0,0,5,58,5,49,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255364,'2026-08-13 03:48:14',1,'dod_anzio','1786590465-TEST',304,316,'kar',0,'#class_axis_kar98','#class_allied_mg',-82,29,-420,-12,692,-406,2,0,0,0,0,4,58,150,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255365,'2026-08-13 03:48:22',1,'dod_anzio','1786590465-TEST',309,314,'bar',0,'#class_allied_heavy','#class_axis_mg34',743,755,-390,1020,912,-382,2,0,0,0,0,16,240,69,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255366,'2026-08-13 03:48:32',1,'dod_anzio','1786590465-TEST',307,306,'greasegun',0,'#class_allied_grease','#class_axis_mp40',-804,739,-412,-259,1355,-264,2,0,0,0,0,28,180,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255367,'2026-08-13 03:48:32',1,'dod_anzio','1786590465-TEST',304,319,'kar',0,'#class_axis_kar98','Random',-220,127,-432,-174,-101,-438,2,0,0,0,0,5,56,7,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255368,'2026-08-13 03:48:34',1,'dod_anzio','1786590465-TEST',307,304,'greasegun',0,'#class_allied_grease','#class_axis_kar98',-628,773,-408,-220,127,-432,2,0,0,0,0,24,180,4,56,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255369,'2026-08-13 03:48:57',1,'dod_anzio','1786590465-TEST',305,317,'colt',0,'#class_allied_garand','#class_axis_pschreck',34,833,-390,149,831,-372,2,0,0,0,0,3,14,4,16,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255370,'2026-08-13 03:48:59',1,'dod_anzio','1786590465-TEST',311,309,'scopedkar',0,'#class_axis_sniper','#class_allied_heavy',-259,1344,-264,-966,855,-422,2,0,0,1,0,4,60,6,235,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255371,'2026-08-13 03:49:10',1,'dod_anzio','1786590465-TEST',305,306,'garand',1,'#class_allied_garand','#class_axis_mp40',124,1118,-390,805,1183,-274,2,0,0,0,0,7,80,1,0,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255372,'2026-08-13 03:49:14',1,'dod_anzio','1786590465-TEST',313,311,'spring',1,'#class_allied_sniper','#class_axis_sniper',-1190,638,-399,-603,999,-404,2,1,0,1,0,5,50,4,58,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255373,'2026-08-13 03:49:24',1,'dod_anzio','1786590465-TEST',313,314,'spring',0,'#class_allied_sniper','#class_axis_mg34',-928,894,-404,-700,922,-422,2,0,0,1,0,2,50,62,375,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255374,'2026-08-13 03:49:27',1,'dod_anzio','1786590465-TEST',319,304,'greasegun',0,'Random','#class_axis_kar98',1016,-271,-332,1296,649,-382,2,0,0,0,0,20,180,3,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255375,'2026-08-13 03:49:42',1,'dod_anzio','1786590465-TEST',319,311,'greasegun',0,'Random','#class_axis_sniper',1384,27,-382,1441,1793,-252,2,1,0,0,0,23,169,4,59,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255376,'2026-08-13 03:49:43',1,'dod_anzio','1786590465-TEST',306,307,'mp40',0,'#class_axis_mp40','#class_allied_grease',1784,746,-278,1247,695,-382,2,0,0,0,0,10,180,29,172,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255377,'2026-08-13 03:50:29',1,'dod_anzio','1786590465-TEST',308,313,'mp44',0,'#class_axis_mp44','#class_allied_sniper',-667,956,-422,-510,421,-422,2,0,0,0,0,22,180,5,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255378,'2026-08-13 03:50:30',1,'dod_anzio','1786590465-TEST',309,308,'bar',1,'#class_allied_heavy','#class_axis_mp44',-1031,341,-364,-683,935,-422,2,0,0,0,0,17,240,17,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255379,'2026-08-13 03:50:41',1,'dod_anzio','1786590465-TEST',304,307,'kar',1,'#class_axis_kar98','#class_allied_grease',1462,-190,-356,887,-756,-441,2,0,0,0,0,5,60,29,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255380,'2026-08-13 03:50:42',1,'dod_anzio','1786590465-TEST',309,317,'bar',0,'#class_allied_heavy','#class_axis_pschreck',-694,922,-404,-258,1159,-398,2,0,0,0,0,18,236,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255381,'2026-08-13 03:50:47',1,'dod_anzio','1786590465-TEST',309,320,'bar',0,'#class_allied_heavy','Random',-694,922,-422,-576,988,-404,2,0,0,0,0,16,236,69,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255382,'2026-08-13 03:50:49',1,'dod_anzio','1786590465-TEST',311,309,'scopedkar',0,'#class_axis_sniper','#class_allied_heavy',-488,1534,-404,-694,922,-404,2,0,0,1,0,5,60,15,236,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255383,'2026-08-13 03:50:56',1,'dod_anzio','1786590465-TEST',319,314,'m1carbine',1,'Random','#class_axis_mg34',1046,-279,-332,1764,-134,-374,2,0,2,0,0,7,150,71,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255384,'2026-08-13 03:51:02',1,'dod_anzio','1786590465-TEST',305,311,'garand',0,'#class_allied_garand','#class_axis_sniper',-627,772,-391,-488,1534,-422,2,0,0,0,0,6,72,0,60,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255385,'2026-08-13 03:51:09',1,'dod_anzio','1786590465-TEST',306,305,'mp40',0,'#class_axis_mp40','#class_allied_garand',-622,867,-404,-644,719,-404,2,0,0,0,0,24,150,4,14,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255386,'2026-08-13 03:51:11',1,'dod_anzio','1786590465-TEST',305,306,'grenade',0,'#class_allied_garand','#class_axis_mp40',-503,-1002,-350,-622,866,-404,2,0,0,0,0,4,0,23,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255387,'2026-08-13 03:51:13',1,'dod_anzio','1786590465-TEST',319,308,'m1carbine',1,'Random','#class_axis_mp44',1046,-279,-332,1770,-79,-356,2,0,0,0,0,9,141,21,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255388,'2026-08-13 03:51:37',1,'dod_anzio','1786590465-TEST',311,307,'scopedkar',0,'#class_axis_sniper','#class_allied_grease',1370,1054,-349,1014,-277,-332,2,0,0,1,0,2,60,30,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255389,'2026-08-13 03:51:39',1,'dod_anzio','1786590465-TEST',311,319,'scopedkar',0,'#class_axis_sniper','Random',1392,952,-372,1046,-279,-332,2,0,0,1,0,1,60,0,119,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255390,'2026-08-13 03:51:43',1,'dod_anzio','1786590465-TEST',313,317,'spring',0,'#class_allied_sniper','#class_axis_pschreck',983,-235,-332,1398,962,-368,2,0,0,1,0,5,50,0,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255391,'2026-08-13 03:51:54',1,'dod_anzio','1786590465-TEST',306,305,'mp40',0,'#class_axis_mp40','#class_allied_garand',-357,1154,-404,-1180,654,-383,2,0,0,0,0,20,180,6,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255392,'2026-08-13 03:52:25',1,'dod_anzio','1786590465-TEST',319,308,'greasegun',0,'Random','#class_axis_mp44',1045,-281,-332,383,-349,-372,2,0,0,0,0,28,180,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255393,'2026-08-13 03:52:33',1,'dod_anzio','1786590465-TEST',320,305,'mp40',0,'Random','#class_allied_garand',-93,90,-419,-271,-192,-372,2,0,0,0,0,21,180,7,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255394,'2026-08-13 03:52:44',1,'dod_anzio','1786590465-TEST',307,320,'greasegun',0,'#class_allied_grease','Random',1031,-269,-332,395,-312,-372,2,0,0,0,0,19,180,0,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255395,'2026-08-13 03:52:46',1,'dod_anzio','1786590465-TEST',307,306,'greasegun',0,'#class_allied_grease','#class_axis_mp40',893,-241,-346,736,-232,-372,2,0,0,0,0,12,180,1,0,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255396,'2026-08-13 03:52:50',1,'dod_anzio','1786590465-TEST',306,319,'grenade2',0,'#class_axis_mp40','Random',1286,2287,-492,1063,-279,-332,2,0,0,0,0,1,0,30,177,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255397,'2026-08-13 03:52:50',1,'dod_anzio','1786590465-TEST',306,313,'grenade2',0,'#class_axis_mp40','#class_allied_sniper',1286,2287,-492,1033,-163,-350,2,0,1,0,0,1,0,4,49,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255398,'2026-08-13 03:52:50',1,'dod_anzio','1786590465-TEST',306,316,'grenade2',0,'#class_axis_mp40','#class_allied_mg',1286,2287,-492,1059,-224,-350,2,0,0,0,0,1,0,147,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255399,'2026-08-13 03:53:26',1,'dod_anzio','1786590465-TEST',319,308,'bazooka',0,'Random','#class_axis_mp44',NULL,NULL,NULL,NULL,NULL,NULL,2,0,0,0,0,-1,-1,-1,-1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255400,'2026-08-13 03:53:30',1,'dod_anzio','1786590465-TEST',317,307,'luger',0,'#class_axis_pschreck','#class_allied_grease',732,-253,-372,1031,-275,-332,2,0,0,0,0,6,16,30,161,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255401,'2026-08-13 03:53:32',1,'dod_anzio','1786590465-TEST',316,317,'30cal',0,'#class_allied_mg','#class_axis_pschreck',604,-338,-390,732,-253,-372,2,0,0,0,0,136,150,0,16,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255402,'2026-08-13 03:53:33',1,'dod_anzio','1786590465-TEST',306,313,'mp40',1,'#class_axis_mp40','#class_allied_sniper',-794,916,-422,-1215,547,-372,2,0,0,0,0,14,180,4,50,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255403,'2026-08-13 03:53:55',1,'dod_anzio','1786590465-TEST',316,320,'30cal',0,'#class_allied_mg','Random',1072,-157,-350,736,-234,-372,2,0,0,0,0,133,150,2,16,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255404,'2026-08-13 03:54:02',1,'dod_anzio','1786590465-TEST',309,317,'bar',0,'#class_allied_heavy','#class_axis_pschreck',1044,-281,-332,1537,751,-333,2,0,0,0,0,11,229,1,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255405,'2026-08-13 03:54:10',1,'dod_anzio','1786590465-TEST',305,306,'garand',0,'#class_allied_garand','#class_axis_mp40',609,-454,-268,701,-716,-311,2,0,0,0,0,3,80,0,163,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255406,'2026-08-13 03:54:27',1,'dod_anzio','1786590465-TEST',317,316,'pschreck',0,'#class_axis_pschreck','#class_allied_mg',NULL,NULL,NULL,NULL,NULL,NULL,2,0,0,0,0,-1,-1,-1,-1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255407,'2026-08-13 03:54:34',1,'dod_anzio','1786590465-TEST',311,305,'scopedkar',0,'#class_axis_sniper','#class_allied_garand',1176,-168,-336,1775,-222,-348,2,0,0,1,0,5,54,1,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255408,'2026-08-13 03:54:57',1,'dod_anzio','1786590465-TEST',306,309,'mp40',0,'#class_axis_mp40','#class_allied_heavy',1768,-95,-374,1044,-281,-332,2,0,0,0,0,16,180,20,214,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255409,'2026-08-13 03:55:06',1,'dod_anzio','1786590465-TEST',305,306,'garand',0,'#class_allied_garand','#class_axis_mp40',536,-349,-372,1133,-193,-318,2,0,0,0,0,7,80,15,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255410,'2026-08-13 03:55:09',1,'dod_anzio','1786590465-TEST',305,317,'garand',0,'#class_allied_garand','#class_axis_pschreck',536,-349,-372,1757,-161,-356,2,0,0,0,0,3,80,0,4,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255411,'2026-08-13 03:55:11',1,'dod_anzio','1786590465-TEST',320,305,'kar',0,'Random','#class_allied_garand',1480,-189,-356,536,-349,-390,2,0,0,0,0,2,60,0,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255412,'2026-08-13 03:55:13',1,'dod_anzio','1786590465-TEST',313,304,'spring',0,'#class_allied_sniper','#class_axis_kar98',1779,-229,-348,1144,-143,-351,2,0,0,1,0,5,50,4,58,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255413,'2026-08-13 03:55:16',1,'dod_anzio','1786590465-TEST',313,314,'spring',0,'#class_allied_sniper','#class_axis_mg34',1779,-229,-348,1177,-136,-354,2,0,1,1,0,4,50,74,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255414,'2026-08-13 03:55:17',1,'dod_anzio','1786590465-TEST',316,308,'30cal',1,'#class_allied_mg','#class_axis_mp44',-1258,141,-390,-1117,679,-387,2,2,0,0,0,149,150,1,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255415,'2026-08-13 03:55:19',1,'dod_anzio','1786590465-TEST',311,313,'scopedkar',1,'#class_axis_sniper','#class_allied_sniper',1176,-168,-336,1779,-229,-366,2,0,1,1,0,3,53,3,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255416,'2026-08-13 03:55:33',1,'dod_anzio','1786590465-TEST',309,320,'bar',0,'#class_allied_heavy','Random',386,-366,-390,1177,-279,-336,2,1,0,0,0,10,240,4,55,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255417,'2026-08-13 03:57:32',1,'dod_anzio','1786590465-TEST',316,304,'30cal',0,'#class_allied_mg','#class_axis_kar98',-987,831,-422,-258,1207,-416,2,2,0,0,0,147,150,2,1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255418,'2026-08-13 03:57:34',1,'dod_anzio','1786590465-TEST',314,309,'mg34',0,'#class_axis_mg34','#class_allied_heavy',1443,-191,-374,1045,-280,-332,2,2,0,0,0,72,375,20,229,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255419,'2026-08-13 03:57:38',1,'dod_anzio','1786590465-TEST',305,314,'garand',0,'#class_allied_garand','#class_axis_mg34',1024,-269,-332,1195,-140,-338,2,0,0,0,0,7,80,71,375,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255420,'2026-08-13 03:57:40',1,'dod_anzio','1786590465-TEST',316,317,'30cal',0,'#class_allied_mg','#class_axis_pschreck',-696,1104,-414,187,1158,-372,2,2,0,0,0,139,150,0,5,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255421,'2026-08-13 03:57:41',1,'dod_anzio','1786590465-TEST',305,311,'grenade',0,'#class_allied_garand','#class_axis_sniper',1024,-269,-350,1163,-158,-353,2,0,1,0,0,4,80,5,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255422,'2026-08-13 03:57:42',1,'dod_anzio','1786590465-TEST',305,308,'garand',0,'#class_allied_garand','#class_axis_mp44',1024,-269,-332,1764,-141,-374,2,0,0,0,0,3,80,8,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255423,'2026-08-13 03:58:00',1,'dod_anzio','1786590465-TEST',320,307,'mg42',0,'Random','#class_allied_grease',891,1186,-284,-36,1191,-390,2,2,0,0,0,240,250,24,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255424,'2026-08-13 03:58:00',1,'dod_anzio','1786590465-TEST',311,305,'scopedkar',0,'#class_axis_sniper','#class_allied_garand',1503,1741,-270,1166,-163,-335,2,0,0,1,0,5,60,2,80,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255425,'2026-08-13 03:58:04',1,'dod_anzio','1786590465-TEST',306,316,'mp40',0,'#class_axis_mp40','#class_allied_mg',889,1185,-266,66,1118,-390,2,0,1,0,0,27,180,150,138,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255426,'2026-08-13 03:58:11',1,'dod_anzio','1786590465-TEST',311,319,'scopedkar',1,'#class_axis_sniper','Random',1512,722,-365,994,-270,-332,2,0,0,1,0,5,59,0,2,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255427,'2026-08-13 03:58:22',1,'dod_anzio','1786590465-TEST',309,320,'bar',0,'#class_allied_heavy','Random',-582,1118,-414,-437,918,-421,2,0,0,0,0,8,240,202,250,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255428,'2026-08-13 03:58:41',1,'dod_anzio','1786590465-TEST',307,308,'greasegun',1,'#class_allied_grease','#class_axis_mp44',388,-380,-390,1122,-286,-332,2,0,0,0,0,26,180,30,175,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255429,'2026-08-13 03:58:46',1,'dod_anzio','1786590465-TEST',311,309,'scopedkar',0,'#class_axis_sniper','#class_allied_heavy',1149,1584,-273,841,1237,-286,2,0,0,0,0,3,58,0,227,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255430,'2026-08-13 03:58:56',1,'dod_anzio','1786590465-TEST',314,307,'mg34',1,'#class_axis_mg34','#class_allied_grease',1670,508,-260,996,-183,-332,2,0,0,0,0,72,375,25,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255431,'2026-08-13 03:59:02',1,'dod_anzio','1786590465-TEST',313,317,'spring',0,'#class_allied_sniper','#class_axis_pschreck',-1184,669,-403,-391,608,-404,2,1,0,1,0,5,50,0,5,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255432,'2026-08-13 03:59:05',1,'dod_anzio','1786590465-TEST',320,313,'mp44',0,'Random','#class_allied_sniper',-285,1157,-422,-1201,714,-410,2,0,0,0,0,22,180,4,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255433,'2026-08-13 03:59:06',1,'dod_anzio','1786590465-TEST',319,320,'spring',0,'Random','Random',-1078,526,-382,-285,1157,-422,2,0,0,1,0,5,50,19,180,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255434,'2026-08-13 03:59:16',1,'dod_anzio','1786590465-TEST',309,306,'bar',0,'#class_allied_heavy','#class_axis_mp40',46,-168,-412,-588,624,-404,2,0,0,0,0,16,240,30,176,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255435,'2026-08-13 03:59:19',1,'dod_anzio','1786590465-TEST',308,316,'mp44',0,'#class_axis_mp44','#class_allied_mg',691,1183,-295,-334,1212,-422,2,0,0,0,0,10,180,150,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255436,'2026-08-13 03:59:30',1,'dod_anzio','1786590465-TEST',311,307,'scopedkar',0,'#class_axis_sniper','#class_allied_grease',-260,1158,-416,-1179,652,-401,2,0,0,1,0,5,54,22,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255437,'2026-08-13 03:59:33',1,'dod_anzio','1786590465-TEST',307,311,'grenade',0,'#class_allied_grease','#class_axis_sniper',-11,-2574,-588,-260,1158,-399,2,0,0,0,0,30,180,4,54,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255438,'2026-08-13 03:59:36',1,'dod_anzio','1786590465-TEST',309,308,'bar',0,'#class_allied_heavy','#class_axis_mp44',-1242,328,-372,-736,922,-404,2,0,0,0,0,20,235,0,180,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255439,'2026-08-13 03:59:43',1,'dod_anzio','1786590465-TEST',318,304,'colt',0,'#class_allied_bazooka','#class_axis_kar98',879,127,-518,895,551,-486,2,0,0,0,0,3,14,5,59,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255440,'2026-08-13 03:59:46',1,'dod_anzio','1786590465-TEST',319,317,'spring',0,'Random','#class_axis_pschreck',-507,1115,-422,528,1189,-324,2,0,0,1,0,2,49,0,5,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255441,'2026-08-13 03:59:49',1,'dod_anzio','1786590465-TEST',320,319,'kar',0,'Random','Random',-256,1358,-264,-507,1115,-422,2,0,0,0,0,4,60,1,49,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255442,'2026-08-13 03:59:51',1,'dod_anzio','1786590465-TEST',309,314,'bar',0,'#class_allied_heavy','#class_axis_mg34',0,835,-390,152,762,-390,2,0,0,0,0,18,234,73,371,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255443,'2026-08-13 03:59:58',1,'dod_anzio','1786590465-TEST',320,313,'kar',0,'Random','#class_allied_sniper',-604,999,-404,-662,791,-408,2,0,0,0,0,2,60,4,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255444,'2026-08-13 04:00:00',1,'dod_anzio','1786590465-TEST',316,320,'30cal',1,'#class_allied_mg','Random',-1098,723,-411,-604,999,-404,2,2,0,0,0,149,150,1,60,1);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255445,'2026-08-13 04:00:05',1,'dod_anzio','1786590465-TEST',309,306,'bar',1,'#class_allied_heavy','#class_axis_mp40',639,1441,-331,188,1780,-378,2,0,1,0,0,9,231,7,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255446,'2026-08-13 04:00:07',1,'dod_anzio','1786590465-TEST',304,309,'kar',0,'#class_axis_kar98','#class_allied_heavy',358,1779,-360,656,1544,-310,2,0,0,0,0,5,60,8,231,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255447,'2026-08-13 04:00:30',1,'dod_anzio','1786590465-TEST',308,316,'mp44',0,'#class_axis_mp44','#class_allied_mg',-701,922,-422,-1181,858,-382,2,1,0,0,0,12,180,148,150,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255448,'2026-08-13 04:00:31',1,'dod_anzio','1786590465-TEST',320,313,'mp44',0,'Random','#class_allied_sniper',1371,928,-372,1060,-158,-332,2,0,0,0,0,24,180,4,50,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255449,'2026-08-13 04:00:36',1,'dod_anzio','1786590465-TEST',307,304,'greasegun',0,'#class_allied_grease','#class_axis_kar98',-176,-103,-420,-16,737,-399,2,0,0,0,0,12,180,4,59,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255450,'2026-08-13 04:00:47',1,'dod_anzio','1786590465-TEST',314,318,'mg34',0,'#class_axis_mg34','#class_allied_bazooka',1174,-276,-354,919,-189,-342,2,0,0,0,0,43,375,0,4,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255451,'2026-08-13 04:00:49',1,'dod_anzio','1786590465-TEST',319,317,'bazooka',0,'Random','#class_axis_pschreck',NULL,NULL,NULL,NULL,NULL,NULL,2,0,0,0,0,-1,-1,-1,-1,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255452,'2026-08-13 04:00:56',1,'dod_anzio','1786590465-TEST',305,306,'garand',0,'#class_allied_garand','#class_axis_mp40',-680,770,-403,-480,1132,-404,2,0,0,0,0,4,80,30,180,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255453,'2026-08-13 04:00:59',1,'dod_anzio','1786590465-TEST',320,307,'mp44',0,'Random','#class_allied_grease',1206,-267,-357,730,-226,-390,2,0,0,0,0,27,150,21,161,0);
INSERT INTO `hlstats_Events_Frags` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `killerId`, `victimId`, `weapon`, `headshot`, `killerRole`, `victimRole`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `half`, `k_prone`, `v_prone`, `k_scope`, `v_scope`, `k_clip`, `k_ammo`, `v_clip`, `v_ammo`, `is_last_flag_defense`) VALUES (1255454,'2026-08-13 04:01:00',1,'dod_anzio','1786590465-TEST',306,305,'grenade2',0,'#class_axis_mp40','#class_allied_garand',2182,1494,-220,-680,770,-403,2,0,0,0,0,30,0,3,80,0);
/*!40000 ALTER TABLE `hlstats_Events_Frags` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Latency`
--

DROP TABLE IF EXISTS `hlstats_Events_Latency`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Latency` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `ping` int unsigned NOT NULL DEFAULT '0',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Latency`
--

LOCK TABLES `hlstats_Events_Latency` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Latency` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_Latency` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_PlayerActions`
--

DROP TABLE IF EXISTS `hlstats_Events_PlayerActions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_PlayerActions` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `actionId` int unsigned NOT NULL DEFAULT '0',
  `bonus` int NOT NULL DEFAULT '0',
  `pos_x` mediumint DEFAULT NULL,
  `pos_y` mediumint DEFAULT NULL,
  `pos_z` mediumint DEFAULT NULL,
  `contester_count` smallint DEFAULT NULL,
  `time_remaining` decimal(6,1) DEFAULT NULL,
  `is_capout` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`),
  KEY `actionId` (`actionId`),
  KEY `idx_match_id_act` (`match_id`)
) ENGINE=MyISAM AUTO_INCREMENT=543931 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_PlayerActions`
--

LOCK TABLES `hlstats_Events_PlayerActions` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_PlayerActions` DISABLE KEYS */;
INSERT INTO `hlstats_Events_PlayerActions` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `contester_count`, `time_remaining`, `is_capout`) VALUES (543928,'2026-08-13 03:23:41',1,'dod_anzio','1786590465-TEST',308,723,0,1497,-193,-356,2,0.0,0);
INSERT INTO `hlstats_Events_PlayerActions` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `contester_count`, `time_remaining`, `is_capout`) VALUES (543929,'2026-08-13 03:28:31',1,'dod_anzio','1786590465-TEST',312,723,0,-392,1155,-422,2,0.5,1);
INSERT INTO `hlstats_Events_PlayerActions` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `contester_count`, `time_remaining`, `is_capout`) VALUES (543930,'2026-08-13 03:50:51',1,'dod_anzio','1786590465-TEST',311,723,0,-488,1534,-418,2,2.4,0);
/*!40000 ALTER TABLE `hlstats_Events_PlayerActions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_PlayerPlayerActions`
--

DROP TABLE IF EXISTS `hlstats_Events_PlayerPlayerActions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_PlayerPlayerActions` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `victimId` int unsigned NOT NULL DEFAULT '0',
  `actionId` int unsigned NOT NULL DEFAULT '0',
  `bonus` int NOT NULL DEFAULT '0',
  `pos_x` mediumint DEFAULT NULL,
  `pos_y` mediumint DEFAULT NULL,
  `pos_z` mediumint DEFAULT NULL,
  `pos_victim_x` mediumint DEFAULT NULL,
  `pos_victim_y` mediumint DEFAULT NULL,
  `pos_victim_z` mediumint DEFAULT NULL,
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`),
  KEY `actionId` (`actionId`),
  KEY `victimId` (`victimId`)
) ENGINE=MyISAM AUTO_INCREMENT=58 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_PlayerPlayerActions`
--

LOCK TABLES `hlstats_Events_PlayerPlayerActions` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_PlayerPlayerActions` DISABLE KEYS */;
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (1,'2026-08-13 03:08:22',1,'dod_anzio',304,318,722,0,33,-2686,-588,-8,652,-392,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (2,'2026-08-13 03:20:21',1,'dod_anzio',313,306,722,0,462,1975,-382,152,762,-390,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (3,'2026-08-13 03:20:51',1,'dod_anzio',309,314,722,0,1007,-244,-350,1474,536,-372,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (4,'2026-08-13 03:21:16',1,'dod_anzio',318,304,722,0,126,-80,-408,-104,-36,-438,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (5,'2026-08-13 03:21:46',1,'dod_anzio',315,307,722,0,-1270,-688,-372,762,-698,-489,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (6,'2026-08-13 03:23:21',1,'dod_anzio',312,314,722,0,2613,3007,-500,1056,-221,-350,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (7,'2026-08-13 03:23:26',1,'dod_anzio',308,305,722,0,1365,767,-372,1171,-273,-336,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (8,'2026-08-13 03:23:36',1,'dod_anzio',317,318,722,0,-576,621,-404,1147,-211,-352,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (9,'2026-08-13 03:24:16',1,'dod_anzio',312,311,722,0,1771,-79,-356,1171,-285,-354,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (10,'2026-08-13 03:25:26',1,'dod_anzio',310,314,722,0,993,1755,-234,-673,930,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (11,'2026-08-13 03:25:41',1,'dod_anzio',308,309,722,0,-395,-2508,-588,-480,-950,-332,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (12,'2026-08-13 03:25:56',1,'dod_anzio',314,307,722,0,-1116,-873,-364,-642,663,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (13,'2026-08-13 03:26:21',1,'dod_anzio',306,305,722,0,-505,-1067,-538,-15,805,-390,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (14,'2026-08-13 03:26:46',1,'dod_anzio',304,312,722,0,-657,773,-398,1075,-224,-326,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (15,'2026-08-13 03:27:01',1,'dod_anzio',307,314,722,0,2692,2731,-500,30,1122,-390,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (16,'2026-08-13 03:28:11',1,'dod_anzio',307,308,722,0,1499,1842,-252,811,1179,-291,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (17,'2026-08-13 03:28:16',1,'dod_anzio',312,304,722,0,368,1442,-360,61,1319,-382,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (18,'2026-08-13 03:29:06',1,'dod_anzio',307,311,722,0,648,1184,-320,-301,1218,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (19,'2026-08-13 03:29:11',1,'dod_anzio',310,317,722,0,2696,2371,-416,0,828,-390,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (20,'2026-08-13 03:29:26',1,'dod_anzio',318,304,722,0,1483,-193,-356,1253,-127,-343,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (21,'2026-08-13 03:29:51',1,'dod_anzio',307,315,722,0,653,1536,-308,-348,1188,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (22,'2026-08-13 03:30:06',1,'dod_anzio',314,318,722,0,-694,1363,-388,1211,1623,-252,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (23,'2026-08-13 03:30:36',1,'dod_anzio',308,309,722,0,0,743,-398,81,839,-372,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (24,'2026-08-13 03:31:11',1,'dod_anzio',316,315,722,0,1762,3119,-440,-733,1094,-414,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (25,'2026-08-13 03:31:11',1,'dod_anzio',305,311,722,0,924,1239,-264,-411,1183,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (26,'2026-08-13 03:32:46',1,'dod_anzio',306,305,722,0,-718,-2193,-624,-1018,677,-405,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (27,'2026-08-13 03:33:21',1,'dod_anzio',304,307,722,0,-947,-866,-357,1286,-70,-518,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (28,'2026-08-13 03:33:26',1,'dod_anzio',315,309,722,0,1747,220,-390,1363,790,-372,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (29,'2026-08-13 03:34:06',1,'dod_anzio',304,312,722,0,-606,-1531,-515,-574,619,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (30,'2026-08-13 03:34:21',1,'dod_anzio',313,311,722,0,1399,1455,-270,1488,753,-381,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (31,'2026-08-13 03:35:16',1,'dod_anzio',305,315,722,0,-575,582,-404,-925,658,-384,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (32,'2026-08-13 03:35:21',1,'dod_anzio',315,305,722,0,-766,-2074,-581,-660,581,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (33,'2026-08-13 03:35:46',1,'dod_anzio',307,308,722,0,402,-160,-372,-162,1145,-390,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (34,'2026-08-13 03:35:51',1,'dod_anzio',306,307,722,0,665,-780,-346,952,-232,-332,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (35,'2026-08-13 03:35:56',1,'dod_anzio',315,316,722,0,-612,-776,-350,-1756,-68,-361,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (36,'2026-08-13 03:36:51',1,'dod_anzio',307,314,722,0,-700,922,-404,-1330,-148,-382,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (37,'2026-08-13 03:37:16',1,'dod_anzio',306,310,722,0,1256,-124,-343,1506,749,-369,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (38,'2026-08-13 03:37:51',1,'dod_anzio',307,304,722,0,-592,671,-422,-586,590,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (39,'2026-08-13 03:39:56',1,'dod_anzio',306,313,722,0,1603,2726,-500,-1022,524,-364,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (40,'2026-08-13 03:41:56',1,'dod_anzio',305,306,722,0,1044,-281,-332,-588,677,-422,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (41,'2026-08-13 03:42:01',1,'dod_anzio',309,314,722,0,-134,94,-436,-930,852,-404,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (42,'2026-08-13 03:42:06',1,'dod_anzio',313,304,722,0,0,763,-395,7,808,-390,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (43,'2026-08-13 03:43:06',1,'dod_anzio',317,309,722,0,1226,1609,-252,916,837,-364,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (44,'2026-08-13 03:45:56',1,'dod_anzio',307,311,722,0,-1253,250,-390,-1192,857,-308,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (45,'2026-08-13 03:46:26',1,'dod_anzio',317,305,722,0,1077,1730,-239,-1321,1229,-365,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (46,'2026-08-13 03:48:36',1,'dod_anzio',319,304,722,0,-628,773,-408,-220,127,-432,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (47,'2026-08-13 03:51:41',1,'dod_anzio',314,319,722,0,1530,751,-327,1046,-279,-332,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (48,'2026-08-13 03:51:46',1,'dod_anzio',319,317,722,0,1059,-224,-350,1398,962,-368,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (49,'2026-08-13 03:53:31',1,'dod_anzio',320,307,722,0,364,1449,-360,1031,-275,-332,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (50,'2026-08-13 03:53:41',1,'dod_anzio',317,305,722,0,1177,-136,-354,1041,-307,-332,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (51,'2026-08-13 03:54:11',1,'dod_anzio',309,306,722,0,1044,-281,-332,701,-716,-311,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (52,'2026-08-13 03:55:01',1,'dod_anzio',320,309,722,0,1336,811,-372,1044,-281,-332,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (53,'2026-08-13 03:57:44',1,'dod_anzio',319,311,722,0,1072,-156,-350,1163,-158,-353,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (54,'2026-08-13 03:58:09',1,'dod_anzio',320,316,722,0,397,1199,-366,66,1118,-390,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (55,'2026-08-13 03:59:34',1,'dod_anzio',308,307,722,0,-398,1155,-422,-1179,652,-401,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (56,'2026-08-13 03:59:39',1,'dod_anzio',307,308,722,0,-552,-2405,-588,-736,922,-404,'1786590465-TEST');
INSERT INTO `hlstats_Events_PlayerPlayerActions` (`id`, `eventTime`, `serverId`, `map`, `playerId`, `victimId`, `actionId`, `bonus`, `pos_x`, `pos_y`, `pos_z`, `pos_victim_x`, `pos_victim_y`, `pos_victim_z`, `match_id`) VALUES (57,'2026-08-13 04:00:09',1,'dod_anzio',314,309,722,0,1550,2560,-500,656,1544,-310,'1786590465-TEST');
/*!40000 ALTER TABLE `hlstats_Events_PlayerPlayerActions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Statsme`
--

DROP TABLE IF EXISTS `hlstats_Events_Statsme`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Statsme` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `weapon` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `shots` int unsigned NOT NULL DEFAULT '0',
  `hits` int unsigned NOT NULL DEFAULT '0',
  `headshots` int unsigned NOT NULL DEFAULT '0',
  `damage` int unsigned NOT NULL DEFAULT '0',
  `kills` int unsigned NOT NULL DEFAULT '0',
  `deaths` int unsigned NOT NULL DEFAULT '0',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `half` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`),
  KEY `weapon` (`weapon`)
) ENGINE=MyISAM AUTO_INCREMENT=320337 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Statsme`
--

LOCK TABLES `hlstats_Events_Statsme` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Statsme` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_Statsme` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Statsme2`
--

DROP TABLE IF EXISTS `hlstats_Events_Statsme2`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Statsme2` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `weapon` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `head` int unsigned NOT NULL DEFAULT '0',
  `chest` int unsigned NOT NULL DEFAULT '0',
  `stomach` int unsigned NOT NULL DEFAULT '0',
  `leftarm` int unsigned NOT NULL DEFAULT '0',
  `rightarm` int unsigned NOT NULL DEFAULT '0',
  `leftleg` int unsigned NOT NULL DEFAULT '0',
  `rightleg` int unsigned NOT NULL DEFAULT '0',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`),
  KEY `weapon` (`weapon`)
) ENGINE=MyISAM AUTO_INCREMENT=319862 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Statsme2`
--

LOCK TABLES `hlstats_Events_Statsme2` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Statsme2` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_Statsme2` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_StatsmeLatency`
--

DROP TABLE IF EXISTS `hlstats_Events_StatsmeLatency`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_StatsmeLatency` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `ping` int unsigned NOT NULL DEFAULT '0',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM AUTO_INCREMENT=57740 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_StatsmeLatency`
--

LOCK TABLES `hlstats_Events_StatsmeLatency` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_StatsmeLatency` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_StatsmeLatency` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_StatsmeTime`
--

DROP TABLE IF EXISTS `hlstats_Events_StatsmeTime`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_StatsmeTime` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `time` time NOT NULL DEFAULT '00:00:00',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM AUTO_INCREMENT=57755 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_StatsmeTime`
--

LOCK TABLES `hlstats_Events_StatsmeTime` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_StatsmeTime` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_StatsmeTime` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Suicides`
--

DROP TABLE IF EXISTS `hlstats_Events_Suicides`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Suicides` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `weapon` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `pos_x` mediumint DEFAULT NULL,
  `pos_y` mediumint DEFAULT NULL,
  `pos_z` mediumint DEFAULT NULL,
  `half` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`),
  KEY `idx_match_id_sui` (`match_id`)
) ENGINE=MyISAM AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Suicides`
--

LOCK TABLES `hlstats_Events_Suicides` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Suicides` DISABLE KEYS */;
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (1,'2026-08-13 03:20:23',1,'dod_anzio','1786590465-TEST',315,'grenade',NULL,NULL,NULL,1);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (2,'2026-08-13 03:21:45',1,'dod_anzio','1786590465-TEST',307,'grenade2',NULL,NULL,NULL,1);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (3,'2026-08-13 03:24:14',1,'dod_anzio','1786590465-TEST',308,'world',NULL,NULL,NULL,1);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (4,'2026-08-13 03:30:26',1,'dod_anzio','1786590465-TEST',310,'grenade2',NULL,NULL,NULL,1);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (5,'2026-08-13 03:32:25',1,'dod_anzio','1786590465-TEST',308,'grenade',NULL,NULL,NULL,1);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (6,'2026-08-13 03:33:16',1,'dod_anzio','1786590465-TEST',307,'world',NULL,NULL,NULL,1);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (7,'2026-08-13 03:36:50',1,'dod_anzio','1786590465-TEST',314,'world',NULL,NULL,NULL,1);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (8,'2026-08-13 03:37:51',1,'dod_anzio','1786590465-TEST',304,'grenade',NULL,NULL,NULL,1);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (9,'2026-08-13 03:40:21',1,'dod_anzio','1786590465-TEST',304,'grenade2',NULL,NULL,NULL,2);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (10,'2026-08-13 03:41:00',1,'dod_anzio','1786590465-TEST',317,'pschreck',NULL,NULL,NULL,2);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (11,'2026-08-13 03:46:21',1,'dod_anzio','1786590465-TEST',305,'world',NULL,NULL,NULL,2);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (12,'2026-08-13 03:46:51',1,'dod_anzio','1786590465-TEST',311,'world',NULL,NULL,NULL,2);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (13,'2026-08-13 03:48:16',1,'dod_anzio','1786590465-TEST',305,'world',NULL,NULL,NULL,2);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (14,'2026-08-13 03:53:37',1,'dod_anzio','1786590465-TEST',305,'grenade',NULL,NULL,NULL,2);
INSERT INTO `hlstats_Events_Suicides` (`id`, `eventTime`, `serverId`, `map`, `match_id`, `playerId`, `weapon`, `pos_x`, `pos_y`, `pos_z`, `half`) VALUES (15,'2026-08-13 03:57:38',1,'dod_anzio','1786590465-TEST',306,'grenade2',NULL,NULL,NULL,2);
/*!40000 ALTER TABLE `hlstats_Events_Suicides` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_TeamBonuses`
--

DROP TABLE IF EXISTS `hlstats_Events_TeamBonuses`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_TeamBonuses` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `actionId` int unsigned NOT NULL DEFAULT '0',
  `bonus` int NOT NULL DEFAULT '0',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `playerId` (`playerId`),
  KEY `actionId` (`actionId`)
) ENGINE=MyISAM AUTO_INCREMENT=1647777 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_TeamBonuses`
--

LOCK TABLES `hlstats_Events_TeamBonuses` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_TeamBonuses` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_TeamBonuses` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Events_Teamkills`
--

DROP TABLE IF EXISTS `hlstats_Events_Teamkills`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Events_Teamkills` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `eventTime` datetime DEFAULT NULL,
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `match_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `killerId` int unsigned NOT NULL DEFAULT '0',
  `victimId` int unsigned NOT NULL DEFAULT '0',
  `weapon` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `pos_x` mediumint DEFAULT NULL,
  `pos_y` mediumint DEFAULT NULL,
  `pos_z` mediumint DEFAULT NULL,
  `pos_victim_x` mediumint DEFAULT NULL,
  `pos_victim_y` mediumint DEFAULT NULL,
  `pos_victim_z` mediumint DEFAULT NULL,
  `half` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `killerId` (`killerId`),
  KEY `idx_match_id_tk` (`match_id`)
) ENGINE=MyISAM AUTO_INCREMENT=31970 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Events_Teamkills`
--

LOCK TABLES `hlstats_Events_Teamkills` WRITE;
/*!40000 ALTER TABLE `hlstats_Events_Teamkills` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Events_Teamkills` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Games`
--

DROP TABLE IF EXISTS `hlstats_Games`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Games` (
  `code` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `hidden` enum('0','1') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  `realgame` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'hl2mp',
  PRIMARY KEY (`code`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Games`
--

LOCK TABLES `hlstats_Games` WRITE;
/*!40000 ALTER TABLE `hlstats_Games` DISABLE KEYS */;
INSERT INTO `hlstats_Games` (`code`, `name`, `hidden`, `realgame`) VALUES ('dod','Day of Defeat','0','dod');
/*!40000 ALTER TABLE `hlstats_Games` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Games_Defaults`
--

DROP TABLE IF EXISTS `hlstats_Games_Defaults`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Games_Defaults` (
  `code` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `parameter` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`code`,`parameter`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Games_Defaults`
--

LOCK TABLES `hlstats_Games_Defaults` WRITE;
/*!40000 ALTER TABLE `hlstats_Games_Defaults` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Games_Defaults` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Games_Supported`
--

DROP TABLE IF EXISTS `hlstats_Games_Supported`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Games_Supported` (
  `code` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`code`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Games_Supported`
--

LOCK TABLES `hlstats_Games_Supported` WRITE;
/*!40000 ALTER TABLE `hlstats_Games_Supported` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Games_Supported` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Heatmap_Config`
--

DROP TABLE IF EXISTS `hlstats_Heatmap_Config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Heatmap_Config` (
  `id` int NOT NULL AUTO_INCREMENT,
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `xoffset` float NOT NULL,
  `yoffset` float NOT NULL,
  `flipx` tinyint(1) NOT NULL DEFAULT '0',
  `flipy` tinyint(1) NOT NULL DEFAULT '1',
  `rotate` tinyint(1) NOT NULL DEFAULT '0',
  `days` tinyint NOT NULL DEFAULT '30',
  `brush` varchar(5) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'small',
  `scale` float NOT NULL,
  `font` tinyint NOT NULL DEFAULT '10',
  `thumbw` float NOT NULL DEFAULT '0.170312',
  `thumbh` float NOT NULL DEFAULT '0.170312',
  `cropx1` int NOT NULL DEFAULT '0',
  `cropy1` int NOT NULL DEFAULT '0',
  `cropx2` int NOT NULL DEFAULT '0',
  `cropy2` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `gamemap` (`map`,`game`)
) ENGINE=MyISAM AUTO_INCREMENT=443 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Heatmap_Config`
--

LOCK TABLES `hlstats_Heatmap_Config` WRITE;
/*!40000 ALTER TABLE `hlstats_Heatmap_Config` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Heatmap_Config` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_HostGroups`
--

DROP TABLE IF EXISTS `hlstats_HostGroups`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_HostGroups` (
  `id` int NOT NULL AUTO_INCREMENT,
  `pattern` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_HostGroups`
--

LOCK TABLES `hlstats_HostGroups` WRITE;
/*!40000 ALTER TABLE `hlstats_HostGroups` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_HostGroups` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Livestats`
--

DROP TABLE IF EXISTS `hlstats_Livestats`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Livestats` (
  `player_id` int NOT NULL DEFAULT '0',
  `server_id` int NOT NULL DEFAULT '0',
  `cli_address` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `cli_city` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `cli_country` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `cli_flag` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `cli_state` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `cli_lat` float(7,4) DEFAULT NULL,
  `cli_lng` float(7,4) DEFAULT NULL,
  `steam_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `name` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `team` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `kills` int NOT NULL DEFAULT '0',
  `deaths` int NOT NULL DEFAULT '0',
  `suicides` int NOT NULL DEFAULT '0',
  `headshots` int NOT NULL DEFAULT '0',
  `shots` int NOT NULL DEFAULT '0',
  `hits` int NOT NULL DEFAULT '0',
  `is_dead` tinyint(1) NOT NULL DEFAULT '0',
  `has_bomb` int NOT NULL DEFAULT '0',
  `ping` int NOT NULL DEFAULT '0',
  `connected` int NOT NULL DEFAULT '0',
  `skill_change` int NOT NULL DEFAULT '0',
  `skill` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`player_id`)
) ENGINE=MEMORY DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Livestats`
--

LOCK TABLES `hlstats_Livestats` WRITE;
/*!40000 ALTER TABLE `hlstats_Livestats` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Livestats` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Maps_Counts`
--

DROP TABLE IF EXISTS `hlstats_Maps_Counts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Maps_Counts` (
  `rowId` int NOT NULL AUTO_INCREMENT,
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `kills` int NOT NULL,
  `headshots` int NOT NULL,
  PRIMARY KEY (`game`,`map`),
  KEY `rowId` (`rowId`)
) ENGINE=MyISAM AUTO_INCREMENT=102 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Maps_Counts`
--

LOCK TABLES `hlstats_Maps_Counts` WRITE;
/*!40000 ALTER TABLE `hlstats_Maps_Counts` DISABLE KEYS */;
INSERT INTO `hlstats_Maps_Counts` (`rowId`, `game`, `map`, `kills`, `headshots`) VALUES (101,'dod','dod_anzio',352,0);
/*!40000 ALTER TABLE `hlstats_Maps_Counts` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Mods_Defaults`
--

DROP TABLE IF EXISTS `hlstats_Mods_Defaults`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Mods_Defaults` (
  `code` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `parameter` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`code`,`parameter`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Mods_Defaults`
--

LOCK TABLES `hlstats_Mods_Defaults` WRITE;
/*!40000 ALTER TABLE `hlstats_Mods_Defaults` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Mods_Defaults` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Mods_Supported`
--

DROP TABLE IF EXISTS `hlstats_Mods_Supported`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Mods_Supported` (
  `code` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`code`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Mods_Supported`
--

LOCK TABLES `hlstats_Mods_Supported` WRITE;
/*!40000 ALTER TABLE `hlstats_Mods_Supported` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Mods_Supported` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Options`
--

DROP TABLE IF EXISTS `hlstats_Options`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Options` (
  `keyname` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `value` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `opttype` tinyint NOT NULL DEFAULT '1',
  PRIMARY KEY (`keyname`),
  KEY `opttype` (`opttype`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Options`
--

LOCK TABLES `hlstats_Options` WRITE;
/*!40000 ALTER TABLE `hlstats_Options` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Options` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Options_Choices`
--

DROP TABLE IF EXISTS `hlstats_Options_Choices`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Options_Choices` (
  `keyname` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `text` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `isDefault` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`keyname`,`value`),
  KEY `keyname` (`keyname`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Options_Choices`
--

LOCK TABLES `hlstats_Options_Choices` WRITE;
/*!40000 ALTER TABLE `hlstats_Options_Choices` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Options_Choices` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_PlayerNames`
--

DROP TABLE IF EXISTS `hlstats_PlayerNames`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_PlayerNames` (
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `name` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `lastuse` datetime DEFAULT NULL,
  `connection_time` int unsigned NOT NULL DEFAULT '0',
  `numuses` int unsigned NOT NULL DEFAULT '0',
  `kills` int unsigned NOT NULL DEFAULT '0',
  `deaths` int unsigned NOT NULL DEFAULT '0',
  `suicides` int unsigned NOT NULL DEFAULT '0',
  `headshots` int unsigned NOT NULL DEFAULT '0',
  `shots` int unsigned NOT NULL DEFAULT '0',
  `hits` int unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`playerId`,`name`),
  KEY `name16` (`name`(16))
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_PlayerNames`
--

LOCK TABLES `hlstats_PlayerNames` WRITE;
/*!40000 ALTER TABLE `hlstats_PlayerNames` DISABLE KEYS */;
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (304,'Bishop','2026-08-13 12:34:02',0,2,25,25,2,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (305,'Ash','2026-08-13 12:34:02',0,2,25,23,3,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (306,'Cutter','2026-08-13 12:34:02',0,2,21,25,1,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (307,'Burke','2026-08-13 12:34:02',0,2,24,26,2,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (308,'Dallas','2026-08-13 12:34:02',0,2,24,26,2,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (309,'Ferro','2026-08-13 12:34:02',0,2,42,20,0,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (310,'Pyramid','2026-08-13 03:38:36',0,1,11,11,1,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (311,'Hicks','2026-08-13 12:34:02',0,2,23,26,1,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (312,'Dracula','2026-08-13 03:38:36',0,1,19,13,0,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (313,'Hudson','2026-08-13 12:34:02',0,2,18,26,0,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (314,'Kane','2026-08-13 12:34:02',0,2,15,27,1,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (315,'Claire','2026-08-13 03:38:36',0,1,30,12,1,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (316,'Lambert','2026-08-13 12:34:02',0,2,19,27,0,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (317,'Ripley','2026-08-13 12:34:02',0,2,12,32,1,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (318,'Parker','2026-08-13 12:34:02',0,2,11,11,0,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (319,'Crash','2026-08-13 12:34:02',0,1,16,10,0,0,0,0);
INSERT INTO `hlstats_PlayerNames` (`playerId`, `name`, `lastuse`, `connection_time`, `numuses`, `kills`, `deaths`, `suicides`, `headshots`, `shots`, `hits`) VALUES (320,'GLaDOS','2026-08-13 12:34:02',0,1,17,12,0,0,0,0);
/*!40000 ALTER TABLE `hlstats_PlayerNames` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_PlayerUniqueIds`
--

DROP TABLE IF EXISTS `hlstats_PlayerUniqueIds`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_PlayerUniqueIds` (
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `uniqueId` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `merge` int unsigned DEFAULT NULL,
  PRIMARY KEY (`uniqueId`,`game`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_PlayerUniqueIds`
--

LOCK TABLES `hlstats_PlayerUniqueIds` WRITE;
/*!40000 ALTER TABLE `hlstats_PlayerUniqueIds` DISABLE KEYS */;
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (304,'BOT:d6b0836b18a32c4f9b0e847ce193a7e9','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (305,'BOT:5298954d716e67cfc8799b20f8724bb2','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (306,'BOT:93dbaacd8732f81ac063f2b6652fd0c8','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (307,'BOT:f2f0618a378b36d44a183a9d0f620571','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (308,'BOT:81ec165ecaefa43b2a2319b9e4db8f6b','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (309,'BOT:409885df9b27db3509fa88a1ba163598','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (310,'BOT:1cf9e8c0b1b28c53a292ea7fd5a539b6','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (311,'BOT:626b7fe8dbe55341efcf9cf7e2af218d','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (312,'BOT:84234c08d780b74b1c3ef6e4e63efab1','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (313,'BOT:70e12814870269ca7b38732fd9a1d045','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (314,'BOT:76de4e788fd3b0481121a386a65d2d79','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (315,'BOT:29211fdf221b8310663d4593517ff8f4','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (316,'BOT:80ceb5d83c51c1f32cbb991e100c46a8','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (317,'BOT:cfa8ec02ca2f90c557de3847a4c07434','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (318,'BOT:971e95fdb817c3ff31f779edfab0b24b','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (319,'BOT:0b3a246a28f5d6814c2c3c262a07c545','dod',NULL);
INSERT INTO `hlstats_PlayerUniqueIds` (`playerId`, `uniqueId`, `game`, `merge`) VALUES (320,'BOT:19d9406a5a093854b7eed879ff0a7045','dod',NULL);
/*!40000 ALTER TABLE `hlstats_PlayerUniqueIds` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Players`
--

DROP TABLE IF EXISTS `hlstats_Players`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Players` (
  `playerId` int unsigned NOT NULL AUTO_INCREMENT,
  `last_event` int NOT NULL DEFAULT '0',
  `connection_time` int unsigned NOT NULL DEFAULT '0',
  `lastName` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `lastAddress` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `city` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `state` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `country` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `flag` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `lat` float(7,4) DEFAULT NULL,
  `lng` float(7,4) DEFAULT NULL,
  `clan` int unsigned NOT NULL DEFAULT '0',
  `kills` int unsigned NOT NULL DEFAULT '0',
  `deaths` int unsigned NOT NULL DEFAULT '0',
  `suicides` int unsigned NOT NULL DEFAULT '0',
  `skill` int unsigned NOT NULL DEFAULT '1000',
  `shots` int unsigned NOT NULL DEFAULT '0',
  `hits` int unsigned NOT NULL DEFAULT '0',
  `teamkills` int unsigned NOT NULL DEFAULT '0',
  `fullName` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `email` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `homepage` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `icq` int unsigned DEFAULT NULL,
  `mmrank` tinyint DEFAULT NULL,
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `hideranking` int unsigned NOT NULL DEFAULT '0',
  `headshots` int unsigned NOT NULL DEFAULT '0',
  `last_skill_change` int NOT NULL DEFAULT '0',
  `displayEvents` int unsigned NOT NULL DEFAULT '1',
  `kill_streak` int NOT NULL DEFAULT '0',
  `death_streak` int NOT NULL DEFAULT '0',
  `blockavatar` int unsigned NOT NULL DEFAULT '0',
  `activity` int NOT NULL DEFAULT '100',
  `createdate` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`playerId`),
  KEY `playerclan` (`clan`,`playerId`),
  KEY `skill` (`skill`),
  KEY `game` (`game`),
  KEY `kills` (`kills`),
  KEY `hideranking` (`hideranking`)
) ENGINE=MyISAM AUTO_INCREMENT=321 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Players`
--

LOCK TABLES `hlstats_Players` WRITE;
/*!40000 ALTER TABLE `hlstats_Players` DISABLE KEYS */;
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (304,1786624445,0,'Bishop','','','','','',NULL,NULL,0,25,25,2,1000,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,0,1,5,3,0,100,1786624423);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (305,1786624445,0,'Ash','','','','','',NULL,NULL,0,25,23,3,1004,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,4,1,3,3,0,100,1786624423);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (306,1786624445,0,'Cutter','','','','','',NULL,NULL,0,21,25,1,992,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,-8,1,4,5,0,100,1786624423);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (307,1786624445,0,'Burke','','','','','',NULL,NULL,0,24,26,2,996,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,-4,1,3,4,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (308,1786624445,0,'Dallas','','','','','',NULL,NULL,0,24,26,2,996,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,-4,1,6,7,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (309,1786624445,0,'Ferro','','','','','',NULL,NULL,0,42,20,0,1044,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,44,1,5,2,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (310,1786624445,0,'Pyramid','','','','','',NULL,NULL,0,11,11,1,1000,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,0,1,4,4,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (311,1786624445,0,'Hicks','','','','','',NULL,NULL,0,23,26,1,994,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,-6,1,4,5,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (312,1786624445,0,'Dracula','','','','','',NULL,NULL,0,19,13,0,1012,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,12,1,6,3,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (313,1786624445,0,'Hudson','','','','','',NULL,NULL,0,18,26,0,984,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,-16,1,2,4,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (314,1786624445,0,'Kane','','','','','',NULL,NULL,0,15,27,1,976,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,-24,1,2,7,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (315,1786624445,0,'Claire','','','','','',NULL,NULL,0,30,12,1,1036,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,36,1,8,4,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (316,1786624445,0,'Lambert','','','','','',NULL,NULL,0,19,27,0,984,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,-16,1,5,5,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (317,1786624445,0,'Ripley','','','','','',NULL,NULL,0,12,32,1,960,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,-40,1,3,10,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (318,1786624445,0,'Parker','','','','','',NULL,NULL,0,11,11,0,1000,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,0,1,5,4,0,100,1786624424);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (319,1786624445,0,'Crash','','','','','',NULL,NULL,0,16,10,0,1012,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,12,1,6,4,0,100,1786624434);
INSERT INTO `hlstats_Players` (`playerId`, `last_event`, `connection_time`, `lastName`, `lastAddress`, `city`, `state`, `country`, `flag`, `lat`, `lng`, `clan`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `teamkills`, `fullName`, `email`, `homepage`, `icq`, `mmrank`, `game`, `hideranking`, `headshots`, `last_skill_change`, `displayEvents`, `kill_streak`, `death_streak`, `blockavatar`, `activity`, `createdate`) VALUES (320,1786624445,0,'GLaDOS','','','','','',NULL,NULL,0,17,12,0,1010,0,0,0,NULL,NULL,NULL,NULL,NULL,'dod',0,0,10,1,5,2,0,100,1786624434);
/*!40000 ALTER TABLE `hlstats_Players` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Players_Awards`
--

DROP TABLE IF EXISTS `hlstats_Players_Awards`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Players_Awards` (
  `awardTime` date NOT NULL,
  `awardId` int unsigned NOT NULL DEFAULT '0',
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `count` int unsigned NOT NULL DEFAULT '0',
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`awardTime`,`awardId`,`playerId`,`game`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Players_Awards`
--

LOCK TABLES `hlstats_Players_Awards` WRITE;
/*!40000 ALTER TABLE `hlstats_Players_Awards` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Players_Awards` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Players_History`
--

DROP TABLE IF EXISTS `hlstats_Players_History`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Players_History` (
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `eventTime` date DEFAULT NULL,
  `connection_time` int unsigned NOT NULL DEFAULT '0',
  `kills` int unsigned NOT NULL DEFAULT '0',
  `deaths` int unsigned NOT NULL DEFAULT '0',
  `suicides` int unsigned NOT NULL DEFAULT '0',
  `skill` int unsigned NOT NULL DEFAULT '1000',
  `shots` int unsigned NOT NULL DEFAULT '0',
  `hits` int unsigned NOT NULL DEFAULT '0',
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `headshots` int unsigned NOT NULL DEFAULT '0',
  `teamkills` int unsigned NOT NULL DEFAULT '0',
  `kill_streak` int NOT NULL DEFAULT '0',
  `death_streak` int NOT NULL DEFAULT '0',
  `skill_change` int NOT NULL DEFAULT '0',
  UNIQUE KEY `eventTime` (`eventTime`,`playerId`,`game`),
  KEY `playerId` (`playerId`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Players_History`
--

LOCK TABLES `hlstats_Players_History` WRITE;
/*!40000 ALTER TABLE `hlstats_Players_History` DISABLE KEYS */;
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (304,'2026-08-13',0,25,25,2,1000,0,0,'dod',0,0,5,3,0);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (305,'2026-08-13',0,25,23,3,1004,0,0,'dod',0,0,3,3,4);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (306,'2026-08-13',0,21,25,1,992,0,0,'dod',0,0,4,5,-8);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (307,'2026-08-13',0,24,26,2,996,0,0,'dod',0,0,3,4,-4);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (308,'2026-08-13',0,24,26,2,996,0,0,'dod',0,0,6,7,-4);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (309,'2026-08-13',0,42,20,0,1044,0,0,'dod',0,0,5,2,44);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (310,'2026-08-13',0,11,11,1,1000,0,0,'dod',0,0,4,4,0);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (311,'2026-08-13',0,23,26,1,994,0,0,'dod',0,0,4,5,-6);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (312,'2026-08-13',0,19,13,0,1012,0,0,'dod',0,0,6,3,12);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (313,'2026-08-13',0,18,26,0,984,0,0,'dod',0,0,2,4,-16);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (314,'2026-08-13',0,15,27,1,976,0,0,'dod',0,0,2,7,-24);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (315,'2026-08-13',0,30,12,1,1036,0,0,'dod',0,0,8,4,36);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (316,'2026-08-13',0,19,27,0,984,0,0,'dod',0,0,5,5,-16);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (317,'2026-08-13',0,12,32,1,960,0,0,'dod',0,0,3,10,-40);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (318,'2026-08-13',0,11,11,0,1000,0,0,'dod',0,0,5,4,0);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (319,'2026-08-13',0,16,10,0,1012,0,0,'dod',0,0,6,4,12);
INSERT INTO `hlstats_Players_History` (`playerId`, `eventTime`, `connection_time`, `kills`, `deaths`, `suicides`, `skill`, `shots`, `hits`, `game`, `headshots`, `teamkills`, `kill_streak`, `death_streak`, `skill_change`) VALUES (320,'2026-08-13',0,17,12,0,1010,0,0,'dod',0,0,5,2,10);
/*!40000 ALTER TABLE `hlstats_Players_History` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Players_Ribbons`
--

DROP TABLE IF EXISTS `hlstats_Players_Ribbons`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Players_Ribbons` (
  `playerId` int unsigned NOT NULL DEFAULT '0',
  `ribbonId` int unsigned NOT NULL DEFAULT '0',
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Players_Ribbons`
--

LOCK TABLES `hlstats_Players_Ribbons` WRITE;
/*!40000 ALTER TABLE `hlstats_Players_Ribbons` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Players_Ribbons` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Ranks`
--

DROP TABLE IF EXISTS `hlstats_Ranks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Ranks` (
  `rankId` int unsigned NOT NULL AUTO_INCREMENT,
  `image` varchar(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `minKills` int unsigned NOT NULL DEFAULT '0',
  `maxKills` int NOT NULL DEFAULT '0',
  `rankName` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`rankId`),
  UNIQUE KEY `rankgame` (`image`,`game`),
  KEY `game` (`game`(8))
) ENGINE=MyISAM AUTO_INCREMENT=1181 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Ranks`
--

LOCK TABLES `hlstats_Ranks` WRITE;
/*!40000 ALTER TABLE `hlstats_Ranks` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Ranks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Ribbons`
--

DROP TABLE IF EXISTS `hlstats_Ribbons`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Ribbons` (
  `ribbonId` int unsigned NOT NULL AUTO_INCREMENT,
  `awardCode` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `awardCount` int NOT NULL DEFAULT '0',
  `special` tinyint NOT NULL DEFAULT '0',
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `image` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `ribbonName` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`ribbonId`),
  UNIQUE KEY `award` (`awardCode`,`awardCount`,`game`,`special`)
) ENGINE=MyISAM AUTO_INCREMENT=1798 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Ribbons`
--

LOCK TABLES `hlstats_Ribbons` WRITE;
/*!40000 ALTER TABLE `hlstats_Ribbons` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Ribbons` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Roles`
--

DROP TABLE IF EXISTS `hlstats_Roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Roles` (
  `roleId` int unsigned NOT NULL AUTO_INCREMENT,
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'valve',
  `code` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `name` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `hidden` enum('0','1') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  `picked` int unsigned NOT NULL DEFAULT '0',
  `kills` int unsigned NOT NULL DEFAULT '0',
  `deaths` int unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`roleId`),
  UNIQUE KEY `gamecode` (`game`,`code`)
) ENGINE=MyISAM AUTO_INCREMENT=161 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Roles`
--

LOCK TABLES `hlstats_Roles` WRITE;
/*!40000 ALTER TABLE `hlstats_Roles` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Roles` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Servers`
--

DROP TABLE IF EXISTS `hlstats_Servers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Servers` (
  `serverId` int unsigned NOT NULL AUTO_INCREMENT,
  `address` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `port` int unsigned NOT NULL DEFAULT '0',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `sortorder` tinyint NOT NULL DEFAULT '0',
  `game` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'valve',
  `publicaddress` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `statusurl` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `kills` int NOT NULL DEFAULT '0',
  `players` int NOT NULL DEFAULT '0',
  `rounds` int NOT NULL DEFAULT '0',
  `suicides` int NOT NULL DEFAULT '0',
  `headshots` int NOT NULL DEFAULT '0',
  `bombs_planted` int NOT NULL DEFAULT '0',
  `bombs_defused` int NOT NULL DEFAULT '0',
  `ct_wins` int NOT NULL DEFAULT '0',
  `ts_wins` int NOT NULL DEFAULT '0',
  `act_players` int NOT NULL DEFAULT '0',
  `max_players` int NOT NULL DEFAULT '0',
  `act_map` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `map_rounds` int NOT NULL DEFAULT '0',
  `map_ct_wins` int NOT NULL DEFAULT '0',
  `map_ts_wins` int NOT NULL DEFAULT '0',
  `map_started` int NOT NULL DEFAULT '0',
  `map_changes` int NOT NULL DEFAULT '0',
  `ct_shots` int NOT NULL DEFAULT '0',
  `ct_hits` int NOT NULL DEFAULT '0',
  `ts_shots` int NOT NULL DEFAULT '0',
  `ts_hits` int NOT NULL DEFAULT '0',
  `map_ct_shots` int NOT NULL DEFAULT '0',
  `map_ct_hits` int NOT NULL DEFAULT '0',
  `map_ts_shots` int NOT NULL DEFAULT '0',
  `map_ts_hits` int NOT NULL DEFAULT '0',
  `lat` float(7,4) DEFAULT NULL,
  `lng` float(7,4) DEFAULT NULL,
  `city` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `country` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `last_event` int unsigned NOT NULL DEFAULT '0',
  `rcon_password` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  PRIMARY KEY (`serverId`),
  UNIQUE KEY `addressport` (`address`,`port`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Servers`
--

LOCK TABLES `hlstats_Servers` WRITE;
/*!40000 ALTER TABLE `hlstats_Servers` DISABLE KEYS */;
INSERT INTO `hlstats_Servers` (`serverId`, `address`, `port`, `name`, `sortorder`, `game`, `publicaddress`, `statusurl`, `kills`, `players`, `rounds`, `suicides`, `headshots`, `bombs_planted`, `bombs_defused`, `ct_wins`, `ts_wins`, `act_players`, `max_players`, `act_map`, `map_rounds`, `map_ct_wins`, `map_ts_wins`, `map_started`, `map_changes`, `ct_shots`, `ct_hits`, `ts_shots`, `ts_hits`, `map_ct_shots`, `map_ct_hits`, `map_ts_shots`, `map_ts_hits`, `lat`, `lng`, `city`, `country`, `last_event`, `rcon_password`) VALUES (1,'127.0.0.1',27015,'KTP Lane B ephemeral',0,'dod','',NULL,352,17,0,15,0,0,0,0,0,14,0,'dod_anzio',0,0,0,1786624434,1,0,0,0,0,0,0,0,0,NULL,NULL,'','',1786624442,'');
/*!40000 ALTER TABLE `hlstats_Servers` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Servers_Config`
--

DROP TABLE IF EXISTS `hlstats_Servers_Config`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Servers_Config` (
  `serverId` int unsigned NOT NULL DEFAULT '0',
  `parameter` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `serverConfigId` int unsigned NOT NULL AUTO_INCREMENT,
  PRIMARY KEY (`serverId`,`parameter`),
  KEY `serverConfigId` (`serverConfigId`)
) ENGINE=MyISAM AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Servers_Config`
--

LOCK TABLES `hlstats_Servers_Config` WRITE;
/*!40000 ALTER TABLE `hlstats_Servers_Config` DISABLE KEYS */;
INSERT INTO `hlstats_Servers_Config` (`serverId`, `parameter`, `value`, `serverConfigId`) VALUES (1,'IgnoreBots','0',1);
INSERT INTO `hlstats_Servers_Config` (`serverId`, `parameter`, `value`, `serverConfigId`) VALUES (1,'MinPlayers','2',2);
INSERT INTO `hlstats_Servers_Config` (`serverId`, `parameter`, `value`, `serverConfigId`) VALUES (1,'BonusRoundIgnore','0',3);
INSERT INTO `hlstats_Servers_Config` (`serverId`, `parameter`, `value`, `serverConfigId`) VALUES (1,'BroadCastEvents','0',4);
INSERT INTO `hlstats_Servers_Config` (`serverId`, `parameter`, `value`, `serverConfigId`) VALUES (1,'PlayerEvents','0',5);
/*!40000 ALTER TABLE `hlstats_Servers_Config` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Servers_Config_Default`
--

DROP TABLE IF EXISTS `hlstats_Servers_Config_Default`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Servers_Config_Default` (
  `parameter` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `value` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` mediumtext CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`parameter`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Servers_Config_Default`
--

LOCK TABLES `hlstats_Servers_Config_Default` WRITE;
/*!40000 ALTER TABLE `hlstats_Servers_Config_Default` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Servers_Config_Default` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Teams`
--

DROP TABLE IF EXISTS `hlstats_Teams`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Teams` (
  `teamId` int unsigned NOT NULL AUTO_INCREMENT,
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'valve',
  `code` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `name` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `hidden` enum('0','1') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  `playerlist_bgcolor` varchar(7) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `playerlist_color` varchar(7) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `playerlist_index` tinyint unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`teamId`),
  UNIQUE KEY `gamecode` (`game`,`code`)
) ENGINE=MyISAM AUTO_INCREMENT=67 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Teams`
--

LOCK TABLES `hlstats_Teams` WRITE;
/*!40000 ALTER TABLE `hlstats_Teams` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Teams` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Trend`
--

DROP TABLE IF EXISTS `hlstats_Trend`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Trend` (
  `timestamp` int NOT NULL DEFAULT '0',
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `players` int NOT NULL DEFAULT '0',
  `kills` int NOT NULL DEFAULT '0',
  `headshots` int NOT NULL DEFAULT '0',
  `servers` int NOT NULL DEFAULT '0',
  `act_slots` int NOT NULL DEFAULT '0',
  `max_slots` int NOT NULL DEFAULT '0',
  KEY `game` (`game`),
  KEY `timestamp` (`timestamp`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Trend`
--

LOCK TABLES `hlstats_Trend` WRITE;
/*!40000 ALTER TABLE `hlstats_Trend` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Trend` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_Weapons`
--

DROP TABLE IF EXISTS `hlstats_Weapons`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_Weapons` (
  `weaponId` int unsigned NOT NULL AUTO_INCREMENT,
  `game` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'valve',
  `code` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `name` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `modifier` float(10,2) NOT NULL DEFAULT '1.00',
  `kills` int unsigned NOT NULL DEFAULT '0',
  `headshots` int unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`weaponId`),
  UNIQUE KEY `gamecode` (`game`,`code`),
  KEY `code` (`code`),
  KEY `modifier` (`modifier`)
) ENGINE=MyISAM AUTO_INCREMENT=939 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_Weapons`
--

LOCK TABLES `hlstats_Weapons` WRITE;
/*!40000 ALTER TABLE `hlstats_Weapons` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_Weapons` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `hlstats_server_load`
--

DROP TABLE IF EXISTS `hlstats_server_load`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `hlstats_server_load` (
  `server_id` int NOT NULL DEFAULT '0',
  `timestamp` int NOT NULL DEFAULT '0',
  `act_players` tinyint NOT NULL DEFAULT '0',
  `min_players` tinyint NOT NULL DEFAULT '0',
  `max_players` tinyint NOT NULL DEFAULT '0',
  `map` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `uptime` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  `fps` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '0',
  KEY `server_id` (`server_id`),
  KEY `timestamp` (`timestamp`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `hlstats_server_load`
--

LOCK TABLES `hlstats_server_load` WRITE;
/*!40000 ALTER TABLE `hlstats_server_load` DISABLE KEYS */;
/*!40000 ALTER TABLE `hlstats_server_load` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_damage_events`
--

DROP TABLE IF EXISTS `ktp_damage_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_damage_events` (
  `id` int NOT NULL AUTO_INCREMENT,
  `server_id` int unsigned NOT NULL,
  `match_id` varchar(64) DEFAULT NULL,
  `half` tinyint NOT NULL DEFAULT '0' COMMENT '0=no match context, 1/2=half, 3+=OT',
  `attacker_id` int NOT NULL,
  `victim_id` int NOT NULL,
  `weapon` varchar(32) NOT NULL,
  `damage` smallint NOT NULL COMMENT 'raw engine value, not clamped to HP',
  `damage_capped` tinyint unsigned NOT NULL COMMENT 'MIN(damage, 100) -- read this one for stats',
  `hitplace` tinyint NOT NULL,
  `game_time` float NOT NULL COMMENT 'get_gametime() at the hit, seconds since map start',
  `event_time` datetime NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_server` (`server_id`),
  KEY `idx_match` (`match_id`),
  KEY `idx_attacker` (`attacker_id`),
  KEY `idx_victim` (`victim_id`),
  KEY `idx_event_time` (`event_time`)
) ENGINE=InnoDB AUTO_INCREMENT=878 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Per-hit damage ledger -- every client_damage hit, capped and raw';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_damage_events`
--

LOCK TABLES `ktp_damage_events` WRITE;
/*!40000 ALTER TABLE `ktp_damage_events` DISABLE KEYS */;
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (1,1,'1786590465-TEST',1,304,318,'m1carbine',30,30,7,65.36,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (2,1,'1786590465-TEST',1,304,318,'m1carbine',30,30,7,65.64,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (3,1,'1786590465-TEST',1,318,304,'luger',30,30,7,65.7,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (4,1,'1786590465-TEST',1,318,304,'luger',30,30,6,66.38,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (5,1,'1786590465-TEST',1,318,304,'luger',30,30,6,66.61,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (6,1,'1786590465-TEST',1,318,304,'luger',30,30,6,66.84,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (7,1,'1786590465-TEST',1,310,308,'mp40',14,14,3,72.76,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (8,1,'1786590465-TEST',1,310,308,'mp40',30,30,6,72.92,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (9,1,'1786590465-TEST',1,310,308,'mp40',40,40,3,73.08,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (10,1,'1786590465-TEST',1,310,308,'mp40',40,40,3,73.24,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (11,1,'1786590465-TEST',1,309,314,'mp44',37,37,6,77.63,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (12,1,'1786590465-TEST',1,309,314,'mp44',37,37,6,77.79,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (13,1,'1786590465-TEST',1,314,309,'30cal',63,63,7,77.89,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (14,1,'1786590465-TEST',1,314,309,'30cal',63,63,7,78.12,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (15,1,'1786590465-TEST',1,315,318,'garand',120,100,3,79.69,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (16,1,'1786590465-TEST',1,309,315,'grenade2',30,30,0,80.97,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (17,1,'1786590465-TEST',1,315,313,'garand',90,90,6,91.61,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (18,1,'1786590465-TEST',1,315,313,'garand',120,100,3,92.89,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (19,1,'1786590465-TEST',1,315,310,'garand',90,90,4,93.74,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (20,1,'1786590465-TEST',1,315,310,'garand',113,100,4,93.74,'2026-08-13 12:33:44','2026-08-13 12:33:44');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (21,1,'1786590465-TEST',1,315,316,'garand',90,90,6,94.56,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (22,1,'1786590465-TEST',1,315,316,'garand',90,90,7,95.2,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (23,1,'1786590465-TEST',1,310,315,'grenade2',23,23,0,98.94,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (24,1,'1786590465-TEST',1,306,312,'greasegun',40,40,2,104.7,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (25,1,'1786590465-TEST',1,306,312,'greasegun',40,40,2,104.92,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (26,1,'1786590465-TEST',1,306,312,'greasegun',30,30,4,105.15,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (27,1,'1786590465-TEST',1,315,307,'garand',41,41,3,118.16,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (28,1,'1786590465-TEST',1,316,317,'mg34',63,63,6,120.69,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (29,1,'1786590465-TEST',1,316,317,'mg34',63,63,7,120.9,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (30,1,'1786590465-TEST',1,315,316,'garand',90,90,6,121.64,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (31,1,'1786590465-TEST',1,315,316,'garand',90,90,7,122.26,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (32,1,'1786590465-TEST',1,315,305,'garand',120,100,2,123.04,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (33,1,'1786590465-TEST',1,315,307,'garand',90,90,7,131.22,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (34,1,'1786590465-TEST',1,306,313,'greasegun',40,40,3,142.31,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (35,1,'1786590465-TEST',1,306,313,'greasegun',40,40,3,143.45,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (36,1,'1786590465-TEST',1,313,306,'luger',30,30,4,143.75,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (37,1,'1786590465-TEST',1,313,306,'luger',30,30,4,144,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (38,1,'1786590465-TEST',1,306,313,'greasegun',30,30,6,144.16,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (39,1,'1786590465-TEST',1,314,314,'mortar',5,5,0,145.49,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (40,1,'1786590465-TEST',1,310,306,'mg34',63,63,7,154.72,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (41,1,'1786590465-TEST',1,315,305,'garand',120,100,3,155.56,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (42,1,'1786590465-TEST',1,315,315,'grenade',47,47,0,158.04,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (43,1,'1786590465-TEST',1,315,316,'grenade',70,70,0,158.04,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (44,1,'1786590465-TEST',1,309,308,'mp44',50,50,3,161.25,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (45,1,'1786590465-TEST',1,309,308,'mp44',50,50,3,161.39,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (46,1,'1786590465-TEST',1,311,311,'mortar',16,16,0,165.22,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (47,1,'1786590465-TEST',1,310,317,'mg34',85,85,2,171.94,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (48,1,'1786590465-TEST',1,310,317,'mg34',63,63,6,172.15,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (49,1,'1786590465-TEST',1,318,311,'luger',100,100,1,177.1,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (50,1,'1786590465-TEST',1,318,314,'luger',30,30,7,183.17,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (51,1,'1786590465-TEST',1,312,312,'mortar',16,16,0,195.64,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (52,1,'1786590465-TEST',1,316,315,'mg34',63,63,6,198.12,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (53,1,'1786590465-TEST',1,316,315,'mg34',63,63,6,198.36,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (54,1,'1786590465-TEST',1,307,308,'mp40',30,30,6,198.83,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (55,1,'1786590465-TEST',1,307,308,'mp40',30,30,6,198.99,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (56,1,'1786590465-TEST',1,307,308,'mp40',30,30,6,199.15,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (57,1,'1786590465-TEST',1,307,308,'mp40',30,30,6,199.32,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (58,1,'1786590465-TEST',1,318,304,'luger',30,30,7,209.14,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (59,1,'1786590465-TEST',1,318,304,'luger',30,30,7,209.34,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (60,1,'1786590465-TEST',1,304,318,'m1carbine',30,30,5,209.42,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (61,1,'1786590465-TEST',1,313,304,'scopedkar',120,100,4,209.47,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (62,1,'1786590465-TEST',1,318,311,'spade',200,100,4,211.79,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (63,1,'1786590465-TEST',1,305,305,'mortar',12,12,0,212.72,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (64,1,'1786590465-TEST',1,309,306,'mp44',37,37,6,221.94,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (65,1,'1786590465-TEST',1,309,306,'mp44',37,37,6,222.09,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (66,1,'1786590465-TEST',1,309,306,'mp44',37,37,6,222.24,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (67,1,'1786590465-TEST',1,315,307,'thompson',30,30,5,233.21,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (68,1,'1786590465-TEST',1,313,314,'scopedkar',160,100,3,233.27,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (69,1,'1786590465-TEST',1,315,307,'thompson',30,30,5,233.38,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (70,1,'1786590465-TEST',1,309,315,'mp44',37,37,5,233.86,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (71,1,'1786590465-TEST',1,309,315,'mp44',37,37,5,234.01,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (72,1,'1786590465-TEST',1,315,307,'thompson',30,30,6,234.16,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (73,1,'1786590465-TEST',1,309,315,'mp44',37,37,4,234.17,'2026-08-13 12:33:45','2026-08-13 12:33:45');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (74,1,'1786590465-TEST',1,311,313,'spring',120,100,7,239.47,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (75,1,'1786590465-TEST',1,307,307,'grenade2',59,59,0,240.49,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (76,1,'1786590465-TEST',1,318,311,'luger',40,40,2,243.77,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (77,1,'1786590465-TEST',1,304,304,'mortar',5,5,0,246.09,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (78,1,'1786590465-TEST',1,308,316,'bar',85,85,3,248.32,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (79,1,'1786590465-TEST',1,308,316,'bar',85,85,3,248.52,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (80,1,'1786590465-TEST',1,318,311,'spade',200,100,4,249.8,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (81,1,'1786590465-TEST',1,312,314,'mg34',21,21,5,293.83,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (82,1,'1786590465-TEST',1,312,314,'mg34',27,27,5,294.02,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (83,1,'1786590465-TEST',1,312,314,'mg34',28,28,5,294.18,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (84,1,'1786590465-TEST',1,315,316,'30cal',63,63,7,295.4,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (85,1,'1786590465-TEST',1,315,316,'30cal',63,63,7,295.55,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (86,1,'1786590465-TEST',1,312,311,'mg34',85,85,2,297.11,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (87,1,'1786590465-TEST',1,312,311,'mg34',85,85,2,297.36,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (88,1,'1786590465-TEST',1,314,314,'mortar',20,20,0,297.75,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (89,1,'1786590465-TEST',1,309,317,'mp44',50,50,2,298.64,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (90,1,'1786590465-TEST',1,309,317,'mp44',50,50,2,298.81,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (91,1,'1786590465-TEST',1,308,309,'bar',47,47,1,299.43,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (92,1,'1786590465-TEST',1,308,309,'bar',31,31,1,299.43,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (93,1,'1786590465-TEST',1,308,309,'bar',47,47,1,299.61,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (94,1,'1786590465-TEST',1,304,307,'grenade',73,73,0,306.04,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (95,1,'1786590465-TEST',1,310,315,'mp40',12,12,6,307.14,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (96,1,'1786590465-TEST',1,310,315,'mp40',30,30,6,308.73,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (97,1,'1786590465-TEST',1,310,315,'mp40',30,30,6,308.89,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (98,1,'1786590465-TEST',1,310,315,'mp40',30,30,6,309.05,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (99,1,'1786590465-TEST',1,310,304,'mp40',31,31,3,309.46,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (100,1,'1786590465-TEST',1,304,310,'m1carbine',30,30,6,309.56,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (101,1,'1786590465-TEST',1,310,304,'mp40',23,23,3,309.62,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (102,1,'1786590465-TEST',1,310,304,'mp40',20,20,3,309.78,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (103,1,'1786590465-TEST',1,310,304,'mp40',20,20,3,309.94,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (104,1,'1786590465-TEST',1,310,304,'mp40',20,20,3,310.1,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (105,1,'1786590465-TEST',1,308,310,'bar',85,85,3,319.58,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (106,1,'1786590465-TEST',1,308,312,'bar',39,39,4,320.72,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (107,1,'1786590465-TEST',1,308,312,'bar',39,39,4,320.92,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (108,1,'1786590465-TEST',1,308,312,'bar',31,31,4,322.24,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (109,1,'1786590465-TEST',1,308,313,'bar',63,63,4,325.99,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (110,1,'1786590465-TEST',1,308,313,'bar',63,63,4,325.99,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (111,1,'1786590465-TEST',1,305,314,'luger',40,40,2,333.17,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (112,1,'1786590465-TEST',1,308,308,'mortar',48,48,0,335.51,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (113,1,'1786590465-TEST',1,308,305,'bar',11,11,4,335.88,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (114,1,'1786590465-TEST',1,308,305,'bar',11,11,4,336.05,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (115,1,'1786590465-TEST',1,308,305,'bar',11,11,4,336.23,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (116,1,'1786590465-TEST',1,309,306,'mp44',37,37,7,336.37,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (117,1,'1786590465-TEST',1,309,306,'mp44',37,37,7,336.51,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (118,1,'1786590465-TEST',1,309,306,'mp44',37,37,7,336.66,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (119,1,'1786590465-TEST',1,308,305,'bar',11,11,4,336.75,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (120,1,'1786590465-TEST',1,308,305,'bar',11,11,4,336.93,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (121,1,'1786590465-TEST',1,308,305,'bar',11,11,4,337.11,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (122,1,'1786590465-TEST',1,318,317,'luger',30,30,7,339.56,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (123,1,'1786590465-TEST',1,318,317,'luger',30,30,6,339.77,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (124,1,'1786590465-TEST',1,317,305,'colt',100,100,1,340,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (125,1,'1786590465-TEST',1,317,318,'colt',30,30,7,340.61,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (126,1,'1786590465-TEST',1,317,318,'colt',30,30,7,340.84,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (127,1,'1786590465-TEST',1,318,317,'luger',30,30,6,344.92,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (128,1,'1786590465-TEST',1,318,317,'luger',30,30,6,345.14,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (129,1,'1786590465-TEST',1,308,318,'bar',63,63,6,350.78,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (130,1,'1786590465-TEST',1,304,316,'m1carbine',30,30,4,351.09,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (131,1,'1786590465-TEST',1,304,316,'m1carbine',30,30,4,351.36,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (132,1,'1786590465-TEST',1,304,316,'m1carbine',30,30,7,351.61,'2026-08-13 12:33:46','2026-08-13 12:33:46');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (133,1,'1786590465-TEST',1,304,316,'m1carbine',30,30,7,351.89,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (134,1,'1786590465-TEST',1,304,309,'m1carbine',30,30,6,352.44,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (135,1,'1786590465-TEST',1,304,309,'m1carbine',30,30,6,352.98,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (136,1,'1786590465-TEST',1,304,309,'m1carbine',40,40,2,353.57,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (137,1,'1786590465-TEST',1,309,304,'grenade2',59,59,0,358.51,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (138,1,'1786590465-TEST',1,312,308,'k43',35,35,1,358.79,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (139,1,'1786590465-TEST',1,312,308,'k43',120,100,3,362.89,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (140,1,'1786590465-TEST',1,312,314,'k43',90,90,7,383.62,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (141,1,'1786590465-TEST',1,310,317,'mp44',37,37,7,385.91,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (142,1,'1786590465-TEST',1,312,314,'k43',90,90,6,386.91,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (143,1,'1786590465-TEST',1,310,317,'mp44',37,37,6,388.05,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (144,1,'1786590465-TEST',1,310,317,'mp44',37,37,6,388.2,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (145,1,'1786590465-TEST',1,312,311,'k43',90,90,6,388.45,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (146,1,'1786590465-TEST',1,316,311,'mg34',63,63,7,390.11,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (147,1,'1786590465-TEST',1,310,306,'mp44',37,37,7,392.73,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (148,1,'1786590465-TEST',1,315,316,'garand',90,90,7,392.78,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (149,1,'1786590465-TEST',1,310,306,'mp44',37,37,6,392.86,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (150,1,'1786590465-TEST',1,310,306,'mp44',37,37,6,393,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (151,1,'1786590465-TEST',1,315,316,'garand',90,90,6,393.42,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (152,1,'1786590465-TEST',1,312,315,'k43',90,90,5,395.6,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (153,1,'1786590465-TEST',1,304,312,'m1carbine',30,30,4,397.87,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (154,1,'1786590465-TEST',1,312,315,'k43',120,100,3,398.96,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (155,1,'1786590465-TEST',1,312,304,'k43',300,100,1,399.67,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (156,1,'1786590465-TEST',1,310,310,'mortar',2,2,0,416.64,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (157,1,'1786590465-TEST',1,310,314,'mp44',37,37,5,417.11,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (158,1,'1786590465-TEST',1,310,314,'mp44',37,37,4,418.23,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (159,1,'1786590465-TEST',1,314,310,'30cal',212,100,1,418.3,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (160,1,'1786590465-TEST',1,313,317,'scopedkar',160,100,2,420.19,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (161,1,'1786590465-TEST',1,308,308,'mortar',22,22,0,429.56,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (162,1,'1786590465-TEST',1,315,318,'bar',63,63,6,432.57,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (163,1,'1786590465-TEST',1,315,318,'bar',63,63,6,432.77,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (164,1,'1786590465-TEST',1,313,315,'scopedkar',160,100,2,434.19,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (165,1,'1786590465-TEST',1,314,313,'30cal',212,100,1,434.23,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (166,1,'1786590465-TEST',1,312,311,'k43',90,90,5,436.28,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (167,1,'1786590465-TEST',1,312,311,'k43',118,100,5,436.28,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (168,1,'1786590465-TEST',1,309,304,'mp44',37,37,4,447.02,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (169,1,'1786590465-TEST',1,309,304,'mp44',125,100,1,447.18,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (170,1,'1786590465-TEST',1,306,305,'greasegun',30,30,7,454.54,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (171,1,'1786590465-TEST',1,306,305,'greasegun',30,30,7,454.78,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (172,1,'1786590465-TEST',1,305,306,'k43',120,100,3,454.96,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (173,1,'1786590465-TEST',1,305,305,'grenade2',19,19,0,457.42,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (174,1,'1786590465-TEST',1,309,317,'mp44',37,37,5,457.54,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (175,1,'1786590465-TEST',1,309,317,'mp44',37,37,7,458.11,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (176,1,'1786590465-TEST',1,309,317,'mp44',37,37,5,458.26,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (177,1,'1786590465-TEST',1,314,307,'30cal',63,63,6,458.59,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (178,1,'1786590465-TEST',1,307,314,'mp40',40,40,2,459.07,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (179,1,'1786590465-TEST',1,308,309,'bar',63,63,6,462.29,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (180,1,'1786590465-TEST',1,309,308,'mp44',50,50,2,464.22,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (181,1,'1786590465-TEST',1,309,308,'mp44',37,37,4,464.37,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (182,1,'1786590465-TEST',1,312,311,'k43',90,90,4,466.11,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (183,1,'1786590465-TEST',1,312,311,'k43',5,5,4,466.11,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (184,1,'1786590465-TEST',1,309,306,'mp44',37,37,4,466.93,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (185,1,'1786590465-TEST',1,312,311,'k43',90,90,6,467.84,'2026-08-13 12:33:47','2026-08-13 12:33:47');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (186,1,'1786590465-TEST',1,306,309,'greasegun',40,40,2,473.18,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (187,1,'1786590465-TEST',1,304,312,'m1carbine',30,30,7,479.4,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (188,1,'1786590465-TEST',1,304,312,'m1carbine',40,40,2,479.67,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (189,1,'1786590465-TEST',1,315,307,'garand',90,90,7,486.1,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (190,1,'1786590465-TEST',1,315,318,'garand',120,100,3,494.18,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (191,1,'1786590465-TEST',1,315,310,'garand',300,100,1,496.65,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (192,1,'1786590465-TEST',1,305,315,'k43butt',150,100,4,502.47,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (193,1,'1786590465-TEST',1,305,308,'k43',120,100,2,505.61,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (194,1,'1786590465-TEST',1,304,305,'m1carbine',30,30,4,514.4,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (195,1,'1786590465-TEST',1,311,309,'spring',120,100,4,524.41,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (196,1,'1786590465-TEST',1,314,318,'30cal',63,63,7,524.94,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (197,1,'1786590465-TEST',1,314,318,'30cal',63,63,7,525.15,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (198,1,'1786590465-TEST',1,307,314,'mp40',30,30,5,526.35,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (199,1,'1786590465-TEST',1,307,314,'mp40',30,30,5,526.48,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (200,1,'1786590465-TEST',1,314,307,'30cal',63,63,6,528.31,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (201,1,'1786590465-TEST',1,314,307,'30cal',63,63,6,528.54,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (202,1,'1786590465-TEST',1,304,312,'m1carbine',30,30,6,532.18,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (203,1,'1786590465-TEST',1,304,312,'m1carbine',30,30,6,532.44,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (204,1,'1786590465-TEST',1,312,304,'scopedkar',160,100,2,533.93,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (205,1,'1786590465-TEST',1,312,317,'luger',30,30,6,538.38,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (206,1,'1786590465-TEST',1,312,317,'luger',30,30,6,538.59,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (207,1,'1786590465-TEST',1,317,312,'colt',40,40,3,538.78,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (208,1,'1786590465-TEST',1,315,316,'m1carbine',30,30,6,540.35,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (209,1,'1786590465-TEST',1,315,316,'m1carbine',30,30,6,540.58,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (210,1,'1786590465-TEST',1,315,316,'m1carbine',30,30,6,540.73,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (211,1,'1786590465-TEST',1,315,316,'m1carbine',30,30,6,540.94,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (212,1,'1786590465-TEST',1,315,313,'m1carbine',23,23,6,541.44,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (213,1,'1786590465-TEST',1,315,313,'m1carbine',23,23,6,541.7,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (214,1,'1786590465-TEST',1,315,313,'m1carbine',12,12,6,541.96,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (215,1,'1786590465-TEST',1,315,313,'m1carbine',30,30,6,542.71,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (216,1,'1786590465-TEST',1,315,313,'m1carbine',30,30,6,542.86,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (217,1,'1786590465-TEST',1,309,314,'mp44',50,50,3,553.44,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (218,1,'1786590465-TEST',1,309,311,'mp44',37,37,7,557.59,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (219,1,'1786590465-TEST',1,309,311,'mp44',37,37,7,557.75,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (220,1,'1786590465-TEST',1,309,311,'mp44',37,37,7,557.9,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (221,1,'1786590465-TEST',1,318,318,'mortar',12,12,0,562.65,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (222,1,'1786590465-TEST',1,318,308,'luger',100,100,1,568.28,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (223,1,'1786590465-TEST',1,317,316,'colt',30,30,6,585.47,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (224,1,'1786590465-TEST',1,317,316,'colt',30,30,6,585.7,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (225,1,'1786590465-TEST',1,317,316,'colt',30,30,6,586.38,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (226,1,'1786590465-TEST',1,317,316,'colt',30,30,6,586.61,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (227,1,'1786590465-TEST',1,311,312,'spring',160,100,3,588.34,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (228,1,'1786590465-TEST',1,304,318,'m1carbine',40,40,3,597.84,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (229,1,'1786590465-TEST',1,304,318,'m1carbine',30,30,6,598.1,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (230,1,'1786590465-TEST',1,304,318,'m1carbine',30,30,6,598.92,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (231,1,'1786590465-TEST',1,305,314,'k43',300,100,1,601.75,'2026-08-13 12:33:48','2026-08-13 12:33:48');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (232,1,'1786590465-TEST',1,307,308,'mp40',37,37,3,604.2,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (233,1,'1786590465-TEST',1,307,308,'mp40',4,4,2,605.36,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (234,1,'1786590465-TEST',1,307,308,'mp40',4,4,2,605.5,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (235,1,'1786590465-TEST',1,307,308,'mp40',4,4,2,605.63,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (236,1,'1786590465-TEST',1,307,308,'mp40',6,6,2,605.77,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (237,1,'1786590465-TEST',1,308,309,'bar',63,63,6,606.66,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (238,1,'1786590465-TEST',1,308,309,'bar',63,63,6,606.84,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (239,1,'1786590465-TEST',1,308,307,'bar',212,100,1,607.44,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (240,1,'1786590465-TEST',1,304,305,'m1carbine',30,30,6,610.33,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (241,1,'1786590465-TEST',1,304,305,'m1carbine',30,30,7,610.6,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (242,1,'1786590465-TEST',1,304,305,'m1carbine',30,30,7,610.87,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (243,1,'1786590465-TEST',1,304,305,'m1carbine',30,30,5,612.23,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (244,1,'1786590465-TEST',1,317,313,'colt',30,30,5,616.69,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (245,1,'1786590465-TEST',1,317,313,'colt',38,38,5,616.69,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (246,1,'1786590465-TEST',1,317,313,'colt',40,40,3,617.1,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (247,1,'1786590465-TEST',1,312,304,'scopedkar',63,63,3,624.53,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (248,1,'1786590465-TEST',1,308,308,'mortar',150,100,0,625.3,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (249,1,'1786590465-TEST',1,304,316,'m1carbine',30,30,6,629.19,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (250,1,'1786590465-TEST',1,316,304,'mg34',63,63,6,629.48,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (251,1,'1786590465-TEST',1,307,307,'grenade2',27,27,0,630.99,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (252,1,'1786590465-TEST',1,315,312,'m1carbine',40,40,3,639.16,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (253,1,'1786590465-TEST',1,315,312,'m1carbine',40,40,3,639.42,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (254,1,'1786590465-TEST',1,315,307,'m1carbine',30,30,5,639.8,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (255,1,'1786590465-TEST',1,312,317,'scopedkar',160,100,2,639.91,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (256,1,'1786590465-TEST',1,315,312,'m1carbine',30,30,7,640.07,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (257,1,'1786590465-TEST',1,315,307,'m1carbine',30,30,5,641.16,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (258,1,'1786590465-TEST',1,307,315,'mp40',30,30,7,641.26,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (259,1,'1786590465-TEST',1,307,315,'mp40',40,40,3,641.4,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (260,1,'1786590465-TEST',1,315,307,'m1carbine',30,30,4,641.42,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (261,1,'1786590465-TEST',1,311,318,'spring',100,100,4,649.81,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (262,1,'1786590465-TEST',1,315,309,'m1carbine',30,30,5,659.2,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (263,1,'1786590465-TEST',1,306,309,'greasegun',11,11,3,659.45,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (264,1,'1786590465-TEST',1,306,309,'greasegun',100,100,1,659.68,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (265,1,'1786590465-TEST',1,308,316,'bar',63,63,6,669.79,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (266,1,'1786590465-TEST',1,308,316,'bar',63,63,6,669.97,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (267,1,'1786590465-TEST',1,307,306,'mp40',29,29,6,671.14,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (268,1,'1786590465-TEST',1,306,307,'greasegun',30,30,7,671.15,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (269,1,'1786590465-TEST',1,307,306,'mp40',29,29,6,671.29,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (270,1,'1786590465-TEST',1,307,306,'mp40',29,29,6,671.44,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (271,1,'1786590465-TEST',1,304,305,'m1carbine',40,40,3,671.95,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (272,1,'1786590465-TEST',1,304,305,'m1carbine',40,40,3,672.23,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (273,1,'1786590465-TEST',1,304,305,'m1carbine',40,40,2,672.53,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (274,1,'1786590465-TEST',1,315,310,'m1carbine',40,40,2,674.58,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (275,1,'1786590465-TEST',1,310,317,'k43',90,90,7,675.12,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (276,1,'1786590465-TEST',1,315,310,'m1carbine',30,30,7,675.42,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (277,1,'1786590465-TEST',1,315,310,'m1carbine',30,30,7,675.57,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (278,1,'1786590465-TEST',1,307,311,'mp40',30,30,6,678.17,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (279,1,'1786590465-TEST',1,307,311,'mp40',30,30,6,678.33,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (280,1,'1786590465-TEST',1,307,311,'mp40',30,30,6,678.48,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (281,1,'1786590465-TEST',1,312,311,'mp40',40,40,2,680.86,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (282,1,'1786590465-TEST',1,312,317,'mp40',30,30,7,683.79,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (283,1,'1786590465-TEST',1,315,307,'m1carbine',30,30,6,685.82,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (284,1,'1786590465-TEST',1,315,307,'m1carbine',30,30,6,686.03,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (285,1,'1786590465-TEST',1,315,307,'m1carbine',30,30,6,686.25,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (286,1,'1786590465-TEST',1,314,318,'30cal',85,85,3,693.7,'2026-08-13 12:33:49','2026-08-13 12:33:49');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (287,1,'1786590465-TEST',1,314,314,'mortar',111,100,0,693.89,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (288,1,'1786590465-TEST',1,318,304,'luger',30,30,7,696.33,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (289,1,'1786590465-TEST',1,318,304,'luger',30,30,7,696.54,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (290,1,'1786590465-TEST',1,312,304,'mp40',30,30,4,699.16,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (291,1,'1786590465-TEST',1,312,304,'mp40',21,21,4,699.16,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (292,1,'1786590465-TEST',1,315,315,'mortar',19,19,0,708.12,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (293,1,'1786590465-TEST',1,312,311,'mp40',40,40,3,709.25,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (294,1,'1786590465-TEST',1,312,311,'mp40',40,40,3,709.4,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (295,1,'1786590465-TEST',1,312,311,'mp40',40,40,3,709.55,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (296,1,'1786590465-TEST',1,315,313,'m1carbine',30,30,5,712.17,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (297,1,'1786590465-TEST',1,315,313,'m1carbine',30,30,4,712.95,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (298,1,'1786590465-TEST',1,315,313,'m1carbine',30,30,4,713.09,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (299,1,'1786590465-TEST',1,315,313,'m1carbine',30,30,4,713.35,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (300,1,'1786590465-TEST',1,315,310,'m1carbine',30,30,6,718.29,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (301,1,'1786590465-TEST',1,315,310,'m1carbine',30,30,6,718.54,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (302,1,'1786590465-TEST',1,315,310,'m1carbine',40,40,3,718.79,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (303,1,'1786590465-TEST',1,310,315,'grenade2',74,74,0,723.99,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (304,1,'1786590465-TEST',1,308,309,'bar',63,63,7,724.3,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (305,1,'1786590465-TEST',1,309,308,'mp44',37,37,6,724.69,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (306,1,'1786590465-TEST',1,309,308,'mp44',37,37,6,724.85,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (307,1,'1786590465-TEST',1,309,308,'mp44',37,37,6,725,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (308,1,'1786590465-TEST',1,307,306,'mp40',30,30,5,732.44,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (309,1,'1786590465-TEST',1,307,306,'mp40',30,30,5,732.6,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (310,1,'1786590465-TEST',1,307,306,'mp40',40,40,2,732.75,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (311,1,'1786590465-TEST',1,306,318,'grenade',21,21,0,737.95,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (312,1,'1786590465-TEST',1,306,307,'grenade',27,27,0,737.95,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (313,1,'1786590465-TEST',1,310,314,'mp44',37,37,4,758.1,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (314,1,'1786590465-TEST',1,310,314,'mp44',37,37,4,758.26,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (315,1,'1786590465-TEST',1,310,314,'mp44',49,49,4,758.26,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (316,1,'1786590465-TEST',1,310,310,'grenade2',81,81,0,760.85,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (317,1,'1786590465-TEST',1,312,304,'mp40',30,30,7,761.05,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (318,1,'1786590465-TEST',1,312,304,'mp40',30,30,7,761.2,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (319,1,'1786590465-TEST',1,312,304,'mp40',30,30,7,761.34,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (320,1,'1786590465-TEST',1,315,305,'spring',120,100,6,761.92,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (321,1,'1786590465-TEST',1,312,304,'mp40',30,30,4,763.06,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (322,1,'1786590465-TEST',1,304,309,'grenade',68,68,0,768.26,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (323,1,'1786590465-TEST',1,308,312,'bar',63,63,5,772.01,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (324,1,'1786590465-TEST',1,308,312,'bar',63,63,5,772.19,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (325,1,'1786590465-TEST',1,315,307,'spring',120,100,5,772.9,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (326,1,'1786590465-TEST',1,308,318,'bar',85,85,2,785.33,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (327,1,'1786590465-TEST',1,308,318,'bar',85,85,2,785.52,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (328,1,'1786590465-TEST',1,316,315,'mg34',63,63,4,786.93,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (329,1,'1786590465-TEST',1,315,316,'spring',400,100,1,787.05,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (330,1,'1786590465-TEST',1,307,308,'mp40',30,30,5,796.05,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (331,1,'1786590465-TEST',1,307,308,'mp40',30,30,5,796.21,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (332,1,'1786590465-TEST',1,307,308,'mp40',30,30,5,796.36,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (333,1,'1786590465-TEST',1,315,310,'spring',120,100,6,797.48,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (334,1,'1786590465-TEST',1,307,308,'mp40',30,30,5,798.05,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (335,1,'1786590465-TEST',1,305,315,'k43',90,90,7,802.34,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (336,1,'1786590465-TEST',1,305,311,'k43',90,90,6,803.13,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (337,1,'1786590465-TEST',1,308,307,'grenade',66,66,0,803.25,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (338,1,'1786590465-TEST',1,309,311,'mp44',37,37,6,804.59,'2026-08-13 12:33:50','2026-08-13 12:33:50');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (339,1,'1786590465-TEST',1,309,317,'mp44',37,37,6,808.98,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (340,1,'1786590465-TEST',1,309,317,'mp44',37,37,6,809.13,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (341,1,'1786590465-TEST',1,309,317,'mp44',37,37,6,809.29,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (342,1,'1786590465-TEST',1,309,314,'mp44',37,37,7,819.34,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (343,1,'1786590465-TEST',1,309,314,'mp44',50,50,2,819.5,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (344,1,'1786590465-TEST',1,309,314,'mp44',37,37,5,819.66,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (345,1,'1786590465-TEST',1,304,312,'grenade',32,32,0,827,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (346,1,'1786590465-TEST',1,304,304,'mortar',5,5,0,869.09,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (347,1,'1786590465-TEST',1,306,313,'greasegun',17,17,6,877.71,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (348,1,'1786590465-TEST',1,306,305,'greasegun',30,30,6,877.72,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (349,1,'1786590465-TEST',1,306,313,'greasegun',17,17,6,877.95,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (350,1,'1786590465-TEST',1,306,305,'greasegun',30,30,6,877.95,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (351,1,'1786590465-TEST',1,313,306,'scopedkar',400,100,1,878.2,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (352,1,'1786590465-TEST',1,308,316,'bar',63,63,7,878.46,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (353,1,'1786590465-TEST',1,308,316,'bar',63,63,7,878.65,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (354,1,'1786590465-TEST',1,308,308,'grenade',75,75,0,879.83,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (355,1,'1786590465-TEST',1,305,311,'grenade2',25,25,0,883.72,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (356,1,'1786590465-TEST',1,305,311,'k43',84,84,3,885.43,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (357,1,'1786590465-TEST',1,304,307,'m1carbine',30,30,7,895.16,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (358,1,'1786590465-TEST',1,317,305,'colt',30,30,4,896.58,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (359,1,'1786590465-TEST',1,317,305,'colt',30,30,4,896.78,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (360,1,'1786590465-TEST',1,312,317,'scopedkar',106,100,3,896.79,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (361,1,'1786590465-TEST',1,307,304,'mp40',30,30,6,897.81,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (362,1,'1786590465-TEST',1,307,304,'mp40',30,30,6,897.95,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (363,1,'1786590465-TEST',1,307,304,'mp40',30,30,6,898.1,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (364,1,'1786590465-TEST',1,304,307,'m1carbine',30,30,7,898.18,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (365,1,'1786590465-TEST',1,307,304,'mp40',40,40,3,898.25,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (366,1,'1786590465-TEST',1,307,314,'mp40',40,40,3,900.78,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (367,1,'1786590465-TEST',1,307,314,'mp40',40,40,3,900.93,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (368,1,'1786590465-TEST',1,307,314,'mp40',40,40,3,901.07,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (369,1,'1786590465-TEST',1,313,313,'mortar',4,4,0,923.21,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (370,1,'1786590465-TEST',1,315,309,'colt',40,40,3,937.23,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (371,1,'1786590465-TEST',1,313,313,'mortar',79,79,0,937.37,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (372,1,'1786590465-TEST',1,315,309,'colt',40,40,3,937.42,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (373,1,'1786590465-TEST',1,311,309,'spring',61,61,3,939.34,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (374,1,'1786590465-TEST',1,305,317,'k43',90,90,7,941.34,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (375,1,'1786590465-TEST',1,305,317,'k43',90,90,4,943.02,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (376,1,'1786590465-TEST',1,314,316,'30cal',63,63,6,950.55,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (377,1,'1786590465-TEST',1,314,316,'30cal',63,63,6,950.79,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (378,1,'1786590465-TEST',1,312,314,'scopedkar',120,100,6,954.06,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (379,1,'1786590465-TEST',1,304,305,'m1carbine',40,40,3,959.43,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (380,1,'1786590465-TEST',1,304,305,'m1carbine',40,40,3,959.72,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (381,1,'1786590465-TEST',1,304,305,'m1carbine',30,30,4,959.98,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (382,1,'1786590465-TEST',1,313,311,'scopedkar',67,67,1,961.67,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (383,1,'1786590465-TEST',1,313,315,'scopedkar',41,41,1,967.81,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (384,1,'1786590465-TEST',1,308,307,'bar',63,63,6,968.32,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (385,1,'1786590465-TEST',1,308,307,'bar',63,63,6,968.51,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (386,1,'1786590465-TEST',1,304,312,'m1carbine',30,30,4,974.64,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (387,1,'1786590465-TEST',1,304,312,'m1carbine',30,30,4,974.94,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (388,1,'1786590465-TEST',1,312,304,'luger',30,30,7,975.43,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (389,1,'1786590465-TEST',1,312,304,'luger',30,30,7,975.64,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (390,1,'1786590465-TEST',1,312,304,'luger',40,40,3,975.88,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (391,1,'1786590465-TEST',1,312,312,'mortar',98,98,0,977.93,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (392,1,'1786590465-TEST',1,313,308,'scopedkar',160,100,2,979.48,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (393,1,'1786590465-TEST',1,306,306,'mortar',23,23,0,984.67,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (394,1,'1786590465-TEST',1,316,311,'mg34',63,63,4,992.48,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (395,1,'1786590465-TEST',1,305,315,'k43',90,90,7,1003.7,'2026-08-13 12:33:51','2026-08-13 12:33:51');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (396,1,'1786590465-TEST',1,305,317,'k43',90,90,7,1006.36,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (397,1,'1786590465-TEST',1,305,317,'k43',120,100,3,1007.25,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (398,1,'1786590465-TEST',1,305,314,'k43',90,90,6,1022.2,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (399,1,'1786590465-TEST',1,305,314,'k43',90,90,6,1023.06,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (400,1,'1786590465-TEST',1,306,309,'greasegun',30,30,4,1030.91,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (401,1,'1786590465-TEST',1,309,306,'mp44',37,37,6,1031.06,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (402,1,'1786590465-TEST',1,309,306,'mp44',37,37,6,1031.22,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (403,1,'1786590465-TEST',1,309,306,'mp44',37,37,6,1031.38,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (404,1,'1786590465-TEST',1,309,304,'mp44',37,37,6,1032.04,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (405,1,'1786590465-TEST',1,309,304,'mp44',37,37,6,1032.2,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (406,1,'1786590465-TEST',1,309,304,'mp44',37,37,6,1032.35,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (407,1,'1786590465-TEST',1,307,311,'mp40',18,18,3,1032.45,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (408,1,'1786590465-TEST',1,307,311,'mp40',18,18,3,1032.61,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (409,1,'1786590465-TEST',1,310,317,'luger',30,30,4,1033.28,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (410,1,'1786590465-TEST',1,311,313,'spring',346,100,4,1033.64,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (411,1,'1786590465-TEST',1,307,311,'mp40',30,30,4,1034.03,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (412,1,'1786590465-TEST',1,307,311,'mp40',10,10,1,1034.8,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (413,1,'1786590465-TEST',1,307,311,'mp40',10,10,1,1034.96,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (414,1,'1786590465-TEST',1,307,311,'mp40',13,13,1,1035.12,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (415,1,'1786590465-TEST',1,307,311,'mp40',30,30,5,1035.28,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (416,1,'1786590465-TEST',1,304,309,'grenade',75,75,0,1037.55,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (417,1,'1786590465-TEST',1,315,316,'m1carbine',30,30,7,1041.05,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (418,1,'1786590465-TEST',1,315,316,'m1carbine',30,30,7,1041.26,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (419,1,'1786590465-TEST',1,315,305,'m1carbine',30,30,6,1042.86,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (420,1,'1786590465-TEST',1,315,305,'m1carbine',30,30,6,1043.09,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (421,1,'1786590465-TEST',1,305,315,'k43',90,90,7,1046.35,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (422,1,'1786590465-TEST',1,310,315,'luger',30,30,7,1047.43,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (423,1,'1786590465-TEST',1,314,305,'30cal',85,85,3,1055.26,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (424,1,'1786590465-TEST',1,316,306,'mg34',85,85,2,1055.97,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (425,1,'1786590465-TEST',1,317,312,'colt',30,30,6,1056.2,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (426,1,'1786590465-TEST',1,316,306,'mg34',85,85,2,1056.2,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (427,1,'1786590465-TEST',1,317,312,'colt',30,30,6,1056.45,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (428,1,'1786590465-TEST',1,307,314,'mp40',30,30,6,1061.6,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (429,1,'1786590465-TEST',1,307,314,'mp40',30,30,6,1061.74,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (430,1,'1786590465-TEST',1,317,312,'colt',23,23,3,1062.87,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (431,1,'1786590465-TEST',1,317,312,'colt',23,23,3,1063.12,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (432,1,'1786590465-TEST',1,307,308,'mp40',30,30,6,1064.07,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (433,1,'1786590465-TEST',1,307,308,'mp40',30,30,6,1064.22,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (434,1,'1786590465-TEST',1,307,308,'mp40',30,30,6,1064.37,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (435,1,'1786590465-TEST',1,309,308,'mp44',37,37,6,1077.03,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (436,1,'1786590465-TEST',1,313,317,'scopedkar',92,92,2,1078.88,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (437,1,'1786590465-TEST',1,306,307,'greasegun',40,40,3,1083.48,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (438,1,'1786590465-TEST',1,306,307,'greasegun',30,30,5,1083.72,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (439,1,'1786590465-TEST',1,314,307,'30cal',63,63,7,1085.02,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (440,1,'1786590465-TEST',1,306,306,'mortar',5,5,0,1086.41,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (441,1,'1786590465-TEST',1,311,310,'spring',120,100,4,1087.44,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (442,1,'1786590465-TEST',1,304,316,'m1carbine',30,30,4,1090,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (443,1,'1786590465-TEST',1,304,316,'m1carbine',22,22,4,1090,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (444,1,'1786590465-TEST',1,309,311,'grenade2',56,56,0,1090.44,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (445,1,'1786590465-TEST',1,312,315,'k43',90,90,5,1109.51,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (446,1,'1786590465-TEST',1,312,315,'k43',90,90,6,1110.37,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (447,1,'1786590465-TEST',1,315,312,'grenade',78,78,0,1115.57,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (448,1,'1786590465-TEST',1,310,304,'mp44',125,100,1,1125.12,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (449,1,'1786590465-TEST',1,304,310,'grenade',79,79,0,1130.32,'2026-08-13 12:33:52','2026-08-13 12:33:52');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (450,1,'1786590465-TEST',1,306,312,'greasegun',100,100,1,1149.01,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (451,1,'1786590465-TEST',1,308,307,'bar',63,63,6,1155.05,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (452,1,'1786590465-TEST',1,308,307,'bar',63,63,6,1155.23,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (453,1,'1786590465-TEST',1,316,316,'mortar',112,100,0,1158.42,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (454,1,'1786590465-TEST',1,305,317,'k43',89,89,6,1159.18,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (455,1,'1786590465-TEST',1,307,308,'grenade2',52,52,0,1160.43,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (456,1,'1786590465-TEST',1,305,317,'k43',90,90,6,1164.45,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (457,1,'1786590465-TEST',1,306,310,'greasegun',30,30,6,1165.74,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (458,1,'1786590465-TEST',1,306,310,'greasegun',30,30,7,1167.33,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (459,1,'1786590465-TEST',1,311,310,'spring',120,100,4,1167.85,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (460,1,'1786590465-TEST',1,312,306,'scopedkar',15,15,1,1178.02,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (461,1,'1786590465-TEST',1,312,306,'scopedkar',3,3,1,1180.69,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (462,1,'1786590465-TEST',1,306,312,'greasegun',40,40,3,1183.08,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (463,1,'1786590465-TEST',1,306,312,'greasegun',40,40,3,1183.33,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (464,1,'1786590465-TEST',1,312,306,'scopedkar',68,68,1,1183.36,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (465,1,'1786590465-TEST',1,306,312,'greasegun',30,30,7,1184.55,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (466,1,'1786590465-TEST',1,305,305,'mortar',12,12,0,1184.72,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (467,1,'1786590465-TEST',1,306,316,'greasegun',100,100,1,1190.12,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (468,1,'1786590465-TEST',1,314,305,'30cal',63,63,7,1199.22,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (469,1,'1786590465-TEST',1,307,314,'mp40',22,22,1,1199.45,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (470,1,'1786590465-TEST',1,314,305,'30cal',63,63,7,1199.46,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (471,1,'1786590465-TEST',1,307,314,'mp40',22,22,1,1199.61,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (472,1,'1786590465-TEST',1,307,314,'mp40',22,22,2,1199.77,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (473,1,'1786590465-TEST',1,307,314,'mp40',40,40,2,1199.91,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (474,1,'1786590465-TEST',1,307,304,'mp40',30,30,5,1201.77,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (475,1,'1786590465-TEST',1,307,304,'mp40',30,30,5,1202.24,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (476,1,'1786590465-TEST',1,304,307,'m1carbine',30,30,5,1205.21,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (477,1,'1786590465-TEST',1,304,307,'m1carbine',30,30,4,1205.48,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (478,1,'1786590465-TEST',1,304,307,'m1carbine',40,40,3,1205.77,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (479,1,'1786590465-TEST',1,304,304,'grenade',61,61,0,1205.82,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (480,1,'1786590465-TEST',1,312,306,'mp40',30,30,6,1217.69,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (481,1,'1786590465-TEST',1,311,312,'spring',160,100,3,1218.32,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (482,1,'1786590465-TEST',1,315,310,'garand',90,90,7,1225.3,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (483,1,'1786590465-TEST',1,315,310,'garand',90,90,6,1225.92,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (484,1,'1786590465-TEST',1,315,305,'garand',300,100,1,1231.52,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (485,1,'1786590465-TEST',1,316,315,'mg34',63,63,5,1235.33,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (486,1,'1786590465-TEST',1,316,315,'mg34',63,63,6,1236.91,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (487,1,'1786590465-TEST',1,304,304,'mortar',5,5,0,1237.81,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (488,1,'1786590465-TEST',1,307,311,'mp40',30,30,4,1237.96,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (489,1,'1786590465-TEST',1,307,311,'mp40',30,30,4,1238.12,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (490,1,'1786590465-TEST',1,307,311,'mp40',40,40,2,1238.28,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (491,1,NULL,0,307,314,'mp40',30,30,6,1247.86,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (492,1,NULL,0,307,314,'mp40',30,30,6,1248.01,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (493,1,NULL,0,307,314,'mp40',30,30,6,1248.17,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (494,1,NULL,0,307,314,'mp40',30,30,7,1250.34,'2026-08-13 12:33:53','2026-08-13 12:33:53');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (495,1,NULL,0,305,305,'mortar',5,5,0,49.58,'2026-08-13 12:33:54','2026-08-13 12:33:54');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (496,1,'1786590465-TEST',2,320,309,'mp44',37,37,7,57.64,'2026-08-13 12:33:54','2026-08-13 12:33:54');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (497,1,'1786590465-TEST',2,320,309,'mp44',37,37,7,57.8,'2026-08-13 12:33:54','2026-08-13 12:33:54');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (498,1,'1786590465-TEST',2,320,309,'mp44',37,37,7,57.95,'2026-08-13 12:33:54','2026-08-13 12:33:54');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (499,1,'1786590465-TEST',2,313,308,'spring',120,100,6,61.07,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (500,1,'1786590465-TEST',2,309,320,'grenade',64,64,0,63.15,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (501,1,'1786590465-TEST',2,309,304,'grenade',76,76,0,63.15,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (502,1,'1786590465-TEST',2,306,313,'mp40',20,20,1,65.51,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (503,1,'1786590465-TEST',2,306,313,'mp40',20,20,1,65.65,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (504,1,'1786590465-TEST',2,306,313,'mp40',20,20,1,65.79,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (505,1,'1786590465-TEST',2,317,317,'mortar',5,5,0,66.08,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (506,1,'1786590465-TEST',2,306,306,'mortar',82,82,0,66.22,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (507,1,'1786590465-TEST',2,319,306,'30cal',63,63,6,66.43,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (508,1,'1786590465-TEST',2,311,313,'scopedkar',400,100,1,79.58,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (509,1,'1786590465-TEST',2,317,305,'luger',30,30,6,89.52,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (510,1,'1786590465-TEST',2,317,305,'luger',22,22,6,95.7,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (511,1,'1786590465-TEST',2,317,305,'luger',22,22,6,95.94,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (512,1,'1786590465-TEST',2,317,305,'spade',60,60,2,97.52,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (513,1,'1786590465-TEST',2,311,319,'scopedkar',400,100,1,99.45,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (514,1,'1786590465-TEST',2,318,306,'colt',100,100,1,100.39,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (515,1,'1786590465-TEST',2,318,304,'colt',40,40,2,104.4,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (516,1,'1786590465-TEST',2,308,318,'mp44',37,37,4,105.27,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (517,1,'1786590465-TEST',2,308,318,'mp44',37,37,4,105.43,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (518,1,'1786590465-TEST',2,308,318,'mp44',37,37,4,105.59,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (519,1,'1786590465-TEST',2,304,304,'grenade2',48,48,0,106.79,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (520,1,'1786590465-TEST',2,308,307,'mp44',37,37,4,115.75,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (521,1,'1786590465-TEST',2,308,307,'mp44',37,37,5,115.9,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (522,1,'1786590465-TEST',2,308,307,'mp44',37,37,5,115.9,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (523,1,'1786590465-TEST',2,320,313,'mp40',40,40,2,117.9,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (524,1,'1786590465-TEST',2,320,313,'mp40',30,30,5,118.06,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (525,1,'1786590465-TEST',2,320,313,'mp40',30,30,5,118.22,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (526,1,'1786590465-TEST',2,314,316,'mg34',212,100,1,126.58,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (527,1,'1786590465-TEST',2,317,317,'mortar',288,100,0,144.91,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (528,1,'1786590465-TEST',2,309,309,'mortar',12,12,0,148.47,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (529,1,'1786590465-TEST',2,305,306,'garand',90,90,4,148.58,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (530,1,'1786590465-TEST',2,306,305,'mp40',40,40,2,149.13,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (531,1,'1786590465-TEST',2,306,305,'mp40',40,40,2,149.29,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (532,1,'1786590465-TEST',2,306,305,'mp40',40,40,2,149.45,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (533,1,'1786590465-TEST',2,304,319,'kar',120,100,6,160.72,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (534,1,'1786590465-TEST',2,316,308,'30cal',63,63,7,161.59,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (535,1,'1786590465-TEST',2,316,308,'30cal',63,63,7,161.82,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (536,1,'1786590465-TEST',2,320,316,'mp40',30,30,6,165.76,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (537,1,'1786590465-TEST',2,320,316,'mp40',30,30,6,165.91,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (538,1,'1786590465-TEST',2,320,316,'spade',45,45,4,166.77,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (539,1,'1786590465-TEST',2,313,320,'colt',20,20,6,167.86,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (540,1,'1786590465-TEST',2,313,320,'colt',20,20,6,168.09,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (541,1,'1786590465-TEST',2,313,320,'colt',30,30,6,168.3,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (542,1,'1786590465-TEST',2,313,320,'colt',30,30,6,168.53,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (543,1,'1786590465-TEST',2,309,306,'bar',63,63,7,200.28,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (544,1,'1786590465-TEST',2,309,314,'bar',63,63,6,201.88,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (545,1,'1786590465-TEST',2,309,311,'bar',85,85,3,202.04,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (546,1,'1786590465-TEST',2,309,311,'bar',85,85,3,202.21,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (547,1,'1786590465-TEST',2,316,314,'30cal',63,63,7,202.71,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (548,1,'1786590465-TEST',2,316,317,'30cal',63,63,6,203.3,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (549,1,'1786590465-TEST',2,316,317,'30cal',63,63,6,203.53,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (550,1,'1786590465-TEST',2,313,304,'amerknife',60,60,2,206.88,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (551,1,'1786590465-TEST',2,304,313,'spade',500,100,1,206.99,'2026-08-13 12:33:55','2026-08-13 12:33:55');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (552,1,'1786590465-TEST',2,307,304,'greasegun',22,22,7,207.26,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (553,1,'1786590465-TEST',2,307,304,'greasegun',26,26,7,207.46,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (554,1,'1786590465-TEST',2,316,320,'30cal',63,63,6,208.28,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (555,1,'1786590465-TEST',2,316,320,'30cal',63,63,6,208.49,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (556,1,'1786590465-TEST',2,308,307,'mp44',50,50,3,214.87,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (557,1,'1786590465-TEST',2,308,307,'mp44',50,50,3,215.01,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (558,1,'1786590465-TEST',2,316,308,'30cal',63,63,5,222.32,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (559,1,'1786590465-TEST',2,316,308,'30cal',212,100,1,223.87,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (560,1,'1786590465-TEST',2,309,309,'grenade',5,5,0,229.66,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (561,1,'1786590465-TEST',2,305,311,'garand',120,100,2,240.51,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (562,1,'1786590465-TEST',2,314,305,'mg34',85,85,3,242.89,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (563,1,'1786590465-TEST',2,314,305,'mg34',85,85,3,243.14,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (564,1,'1786590465-TEST',2,317,309,'luger',30,30,4,248.18,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (565,1,'1786590465-TEST',2,309,317,'bar',63,63,7,248.23,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (566,1,'1786590465-TEST',2,317,309,'luger',30,30,4,248.4,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (567,1,'1786590465-TEST',2,309,317,'bar',63,63,7,248.41,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (568,1,'1786590465-TEST',2,313,314,'spring',120,100,6,250.58,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (569,1,'1786590465-TEST',2,304,313,'kar',85,85,3,255.78,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (570,1,'1786590465-TEST',2,304,313,'kar',64,64,3,261.03,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (571,1,'1786590465-TEST',2,308,309,'mp44',37,37,7,267.48,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (572,1,'1786590465-TEST',2,320,307,'mg34',63,63,7,272.65,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (573,1,'1786590465-TEST',2,307,320,'greasegun',30,30,6,272.8,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (574,1,'1786590465-TEST',2,320,307,'mg34',63,63,7,272.85,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (575,1,'1786590465-TEST',2,316,320,'30cal',63,63,6,286.09,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (576,1,'1786590465-TEST',2,316,320,'30cal',63,63,4,286.33,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (577,1,'1786590465-TEST',2,316,316,'mortar',68,68,0,304.2,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (578,1,'1786590465-TEST',2,313,311,'spring',3,3,2,305.56,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (579,1,'1786590465-TEST',2,304,305,'kar',160,100,3,305.62,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (580,1,'1786590465-TEST',2,311,313,'scopedkar',120,100,6,307.79,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (581,1,'1786590465-TEST',2,309,317,'bar',63,63,6,311.54,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (582,1,'1786590465-TEST',2,309,317,'bar',63,63,6,311.73,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (583,1,'1786590465-TEST',2,308,309,'mp44',37,37,4,320.37,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (584,1,'1786590465-TEST',2,309,308,'bar',212,100,1,322.81,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (585,1,'1786590465-TEST',2,319,320,'garand',120,100,3,334.12,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (586,1,'1786590465-TEST',2,319,311,'garand',83,83,3,336.98,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (587,1,'1786590465-TEST',2,319,311,'garand',90,90,6,337.66,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (588,1,'1786590465-TEST',2,319,306,'garand',90,90,6,338.56,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (589,1,'1786590465-TEST',2,319,306,'garand',90,90,6,339.24,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (590,1,'1786590465-TEST',2,319,317,'garand',120,100,2,344,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (591,1,'1786590465-TEST',2,319,314,'garand',90,90,6,350.86,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (592,1,'1786590465-TEST',2,319,314,'garand',90,90,7,351.53,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (593,1,'1786590465-TEST',2,307,304,'greasegun',30,30,4,356.5,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (594,1,'1786590465-TEST',2,307,304,'greasegun',40,40,3,356.92,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (595,1,'1786590465-TEST',2,308,313,'mp44',50,50,3,359.32,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (596,1,'1786590465-TEST',2,308,313,'mp44',50,50,3,359.59,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (597,1,'1786590465-TEST',2,319,308,'colt',30,30,4,360.43,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (598,1,'1786590465-TEST',2,319,308,'colt',30,30,4,360.58,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (599,1,'1786590465-TEST',2,319,308,'colt',30,30,4,360.73,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (600,1,'1786590465-TEST',2,319,308,'colt',30,30,6,360.91,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (601,1,'1786590465-TEST',2,319,320,'colt',40,40,2,368.01,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (602,1,'1786590465-TEST',2,320,319,'k43',90,90,6,369.46,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (603,1,'1786590465-TEST',2,320,319,'k43',90,90,6,370.28,'2026-08-13 12:33:56','2026-08-13 12:33:56');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (604,1,'1786590465-TEST',2,320,316,'grenade2',9,9,0,370.89,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (605,1,'1786590465-TEST',2,307,304,'greasegun',40,40,3,370.97,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (606,1,'1786590465-TEST',2,320,316,'k43',120,100,3,387.14,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (607,1,'1786590465-TEST',2,314,307,'mg34',85,85,2,400.83,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (608,1,'1786590465-TEST',2,314,307,'mg34',85,85,2,401.07,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (609,1,'1786590465-TEST',2,311,313,'scopedkar',354,100,7,401.99,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (610,1,'1786590465-TEST',2,309,314,'bar',85,85,3,403.63,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (611,1,'1786590465-TEST',2,309,314,'bar',32,32,3,403.81,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (612,1,'1786590465-TEST',2,309,304,'bar',63,63,6,411.01,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (613,1,'1786590465-TEST',2,309,304,'bar',63,63,6,411.17,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (614,1,'1786590465-TEST',2,308,319,'mp44',37,37,6,420.56,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (615,1,'1786590465-TEST',2,308,319,'mp44',50,50,2,420.71,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (616,1,'1786590465-TEST',2,308,319,'mp44',50,50,2,420.85,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (617,1,'1786590465-TEST',2,305,317,'garand',90,90,6,422.25,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (618,1,'1786590465-TEST',2,317,305,'luger',30,30,4,422.77,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (619,1,'1786590465-TEST',2,317,305,'luger',30,30,4,422.99,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (620,1,'1786590465-TEST',2,317,305,'luger',9,9,4,423.23,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (621,1,'1786590465-TEST',2,317,305,'luger',9,9,4,423.43,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (622,1,'1786590465-TEST',2,305,317,'garand',90,90,4,426.07,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (623,1,'1786590465-TEST',2,320,309,'k43',14,14,3,430.65,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (624,1,'1786590465-TEST',2,320,309,'k43',12,12,2,431.43,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (625,1,'1786590465-TEST',2,320,309,'k43',17,17,2,432.24,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (626,1,'1786590465-TEST',2,306,309,'mp40',40,40,2,433.41,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (627,1,'1786590465-TEST',2,307,311,'greasegun',30,30,6,436.67,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (628,1,'1786590465-TEST',2,307,311,'greasegun',30,30,7,436.9,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (629,1,'1786590465-TEST',2,313,311,'spring',160,100,3,436.91,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (630,1,'1786590465-TEST',2,309,306,'grenade',7,7,0,437.35,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (631,1,'1786590465-TEST',2,309,314,'bar',63,63,7,482.8,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (632,1,'1786590465-TEST',2,309,314,'bar',63,63,7,482.98,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (633,1,'1786590465-TEST',2,320,313,'k43',8,8,1,484.48,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (634,1,'1786590465-TEST',2,306,316,'mp40',30,30,7,484.62,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (635,1,'1786590465-TEST',2,306,316,'mp40',30,30,7,484.78,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (636,1,'1786590465-TEST',2,306,316,'mp40',30,30,7,484.93,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (637,1,'1786590465-TEST',2,313,306,'colt',30,30,6,485.15,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (638,1,'1786590465-TEST',2,313,306,'colt',30,30,6,485.36,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (639,1,'1786590465-TEST',2,320,313,'k43',90,90,4,486.14,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (640,1,'1786590465-TEST',2,320,313,'k43',58,58,4,486.14,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (641,1,'1786590465-TEST',2,306,316,'mp40',30,30,7,487.12,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (642,1,'1786590465-TEST',2,307,317,'greasegun',30,30,7,494.84,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (643,1,'1786590465-TEST',2,307,317,'greasegun',30,30,7,495.07,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (644,1,'1786590465-TEST',2,307,317,'greasegun',30,30,7,495.31,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (645,1,'1786590465-TEST',2,307,317,'greasegun',100,100,1,495.55,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (646,1,'1786590465-TEST',2,309,304,'bar',25,25,2,501.97,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (647,1,'1786590465-TEST',2,309,304,'bar',25,25,2,502.14,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (648,1,'1786590465-TEST',2,309,304,'bar',25,25,2,502.3,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (649,1,'1786590465-TEST',2,309,304,'bar',20,20,2,504.4,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (650,1,'1786590465-TEST',2,309,304,'bar',20,20,2,504.57,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (651,1,'1786590465-TEST',2,307,314,'greasegun',30,30,7,508.78,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (652,1,'1786590465-TEST',2,307,314,'greasegun',30,30,7,509,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (653,1,'1786590465-TEST',2,307,314,'greasegun',30,30,6,509.22,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (654,1,'1786590465-TEST',2,307,314,'greasegun',30,30,6,509.44,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (655,1,'1786590465-TEST',2,320,319,'k43',90,90,7,520.36,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (656,1,'1786590465-TEST',2,307,317,'greasegun',100,100,1,521.04,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (657,1,'1786590465-TEST',2,320,319,'k43',49,49,5,521.15,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (658,1,'1786590465-TEST',2,304,316,'kar',44,44,1,533.8,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (659,1,'1786590465-TEST',2,304,316,'kar',26,26,1,533.8,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (660,1,'1786590465-TEST',2,320,307,'k43',90,90,5,534.11,'2026-08-13 12:33:57','2026-08-13 12:33:57');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (661,1,'1786590465-TEST',2,320,307,'k43',90,90,7,534.92,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (662,1,'1786590465-TEST',2,304,316,'kar',47,47,4,536.6,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (663,1,'1786590465-TEST',2,304,309,'bayonet',200,100,4,539.38,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (664,1,'1786590465-TEST',2,313,306,'spring',120,100,7,551.27,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (665,1,'1786590465-TEST',2,309,311,'bar',63,63,7,576.02,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (666,1,'1786590465-TEST',2,309,311,'bar',63,63,6,576.22,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (667,1,'1786590465-TEST',2,304,313,'kar',160,100,3,576.93,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (668,1,'1786590465-TEST',2,304,316,'kar',160,100,3,579.4,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (669,1,'1786590465-TEST',2,309,314,'bar',63,63,6,587.3,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (670,1,'1786590465-TEST',2,309,314,'bar',63,63,6,587.47,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (671,1,'1786590465-TEST',2,319,304,'garand',90,90,7,597.36,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (672,1,'1786590465-TEST',2,307,306,'greasegun',40,40,2,597.41,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (673,1,'1786590465-TEST',2,307,306,'greasegun',30,30,4,597.66,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (674,1,'1786590465-TEST',2,307,306,'greasegun',38,38,4,597.66,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (675,1,'1786590465-TEST',2,304,319,'kar',120,100,5,597.66,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (676,1,'1786590465-TEST',2,307,304,'greasegun',40,40,3,599.13,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (677,1,'1786590465-TEST',2,305,317,'garand',60,60,3,618.84,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (678,1,'1786590465-TEST',2,305,317,'colt',30,30,6,621.4,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (679,1,'1786590465-TEST',2,305,317,'colt',30,30,7,622.29,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (680,1,'1786590465-TEST',2,311,309,'scopedkar',160,100,2,624.32,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (681,1,'1786590465-TEST',2,311,311,'mortar',12,12,0,631.66,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (682,1,'1786590465-TEST',2,305,306,'garand',300,100,1,635.46,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (683,1,'1786590465-TEST',2,313,311,'spring',400,100,1,639.17,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (684,1,'1786590465-TEST',2,313,314,'spring',120,100,4,649.4,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (685,1,'1786590465-TEST',2,304,319,'kar',11,11,5,650.47,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (686,1,'1786590465-TEST',2,319,304,'greasegun',9,9,4,651.49,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (687,1,'1786590465-TEST',2,319,304,'greasegun',8,8,4,651.49,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (688,1,'1786590465-TEST',2,319,304,'greasegun',9,9,4,651.73,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (689,1,'1786590465-TEST',2,319,304,'greasegun',30,30,4,652.4,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (690,1,'1786590465-TEST',2,319,304,'greasegun',40,40,2,652.62,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (691,1,'1786590465-TEST',2,319,304,'greasegun',40,40,2,652.84,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (692,1,'1786590465-TEST',2,319,311,'greasegun',40,40,2,667.35,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (693,1,'1786590465-TEST',2,319,311,'greasegun',40,40,2,667.57,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (694,1,'1786590465-TEST',2,319,311,'greasegun',30,30,4,667.78,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (695,1,'1786590465-TEST',2,306,307,'mp40',40,40,3,668.16,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (696,1,'1786590465-TEST',2,306,307,'mp40',40,40,3,668.29,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (697,1,'1786590465-TEST',2,306,307,'mp40',40,40,3,668.43,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (698,1,'1786590465-TEST',2,308,313,'mp44',50,50,3,713.9,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (699,1,'1786590465-TEST',2,308,313,'mp44',50,50,3,714.06,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (700,1,'1786590465-TEST',2,309,308,'bar',212,100,1,715.52,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (701,1,'1786590465-TEST',2,304,307,'kar',400,100,1,726.36,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (702,1,'1786590465-TEST',2,309,317,'bar',63,63,6,727.24,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (703,1,'1786590465-TEST',2,309,317,'bar',63,63,6,727.4,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (704,1,'1786590465-TEST',2,309,320,'bar',63,63,7,731.85,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (705,1,'1786590465-TEST',2,309,320,'bar',85,85,2,732.02,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (706,1,'1786590465-TEST',2,311,309,'scopedkar',120,100,6,734.26,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (707,1,'1786590465-TEST',2,319,314,'m1carbine',30,30,7,739.55,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (708,1,'1786590465-TEST',2,314,319,'mg34',85,85,3,741.33,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (709,1,'1786590465-TEST',2,319,314,'m1carbine',100,100,1,741.49,'2026-08-13 12:33:58','2026-08-13 12:33:58');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (710,1,'1786590465-TEST',2,306,305,'mp40',30,30,4,742.02,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (711,1,'1786590465-TEST',2,305,311,'garand',90,90,6,745.48,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (712,1,'1786590465-TEST',2,305,311,'garand',90,90,6,747.38,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (713,1,'1786590465-TEST',2,306,305,'mp40',30,30,4,748.46,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (714,1,'1786590465-TEST',2,306,305,'mp40',39,39,4,748.46,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (715,1,'1786590465-TEST',2,306,305,'mp40',30,30,7,753.89,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (716,1,'1786590465-TEST',2,305,306,'grenade',70,70,0,756.66,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (717,1,'1786590465-TEST',2,319,308,'m1carbine',100,100,1,757.99,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (718,1,'1786590465-TEST',2,319,311,'m1carbine',40,40,2,772.17,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (719,1,'1786590465-TEST',2,319,317,'m1carbine',15,15,2,772.17,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (720,1,'1786590465-TEST',2,319,311,'m1carbine',30,30,5,772.45,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (721,1,'1786590465-TEST',2,319,317,'m1carbine',9,9,5,772.45,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (722,1,'1786590465-TEST',2,311,307,'scopedkar',65,65,1,778.59,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (723,1,'1786590465-TEST',2,319,317,'m1carbine',27,27,1,781.2,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (724,1,'1786590465-TEST',2,319,317,'m1carbine',27,27,1,781.43,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (725,1,'1786590465-TEST',2,311,307,'scopedkar',65,65,3,782.15,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (726,1,'1786590465-TEST',2,311,319,'scopedkar',86,86,3,784.66,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (727,1,'1786590465-TEST',2,313,317,'spring',120,100,5,788.01,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (728,1,'1786590465-TEST',2,306,305,'mp40',30,30,5,798.6,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (729,1,'1786590465-TEST',2,306,305,'mp40',30,30,5,798.74,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (730,1,'1786590465-TEST',2,306,305,'mp40',30,30,5,798.88,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (731,1,'1786590465-TEST',2,306,305,'mp40',30,30,5,799.02,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (732,1,'1786590465-TEST',2,319,308,'greasegun',30,30,4,829.63,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (733,1,'1786590465-TEST',2,319,308,'greasegun',30,30,4,829.87,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (734,1,'1786590465-TEST',2,319,308,'greasegun',30,30,4,830.1,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (735,1,'1786590465-TEST',2,319,308,'greasegun',23,23,4,830.1,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (736,1,'1786590465-TEST',2,320,305,'mp40',30,30,6,838.14,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (737,1,'1786590465-TEST',2,320,305,'mp40',30,30,6,838.27,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (738,1,'1786590465-TEST',2,320,305,'mp40',30,30,6,838.41,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (739,1,'1786590465-TEST',2,320,305,'mp40',30,30,6,838.55,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (740,1,'1786590465-TEST',2,320,307,'mp40',30,30,7,844.62,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (741,1,'1786590465-TEST',2,320,307,'mp40',30,30,7,844.78,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (742,1,'1786590465-TEST',2,320,307,'mp40',30,30,7,844.93,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (743,1,'1786590465-TEST',2,307,320,'greasegun',40,40,3,849,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (744,1,'1786590465-TEST',2,307,320,'greasegun',40,40,3,849.23,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (745,1,'1786590465-TEST',2,307,320,'greasegun',40,40,3,849.46,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (746,1,'1786590465-TEST',2,307,306,'greasegun',30,30,6,850.11,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (747,1,'1786590465-TEST',2,307,306,'greasegun',30,30,6,850.34,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (748,1,'1786590465-TEST',2,307,306,'greasegun',40,40,2,851.49,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (749,1,'1786590465-TEST',2,306,319,'grenade2',55,55,0,855.71,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (750,1,'1786590465-TEST',2,306,313,'grenade2',80,80,0,855.71,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (751,1,'1786590465-TEST',2,306,316,'grenade2',83,83,0,855.71,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (752,1,'1786590465-TEST',2,308,308,'mortar',12,12,0,875.82,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (753,1,'1786590465-TEST',2,308,308,'mortar',88,88,0,891.69,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (754,1,'1786590465-TEST',2,317,307,'luger',30,30,5,895.16,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (755,1,'1786590465-TEST',2,317,305,'luger',30,30,7,895.74,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (756,1,'1786590465-TEST',2,317,305,'luger',30,30,7,895.97,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (757,1,'1786590465-TEST',2,306,313,'mp40',30,30,6,897.45,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (758,1,'1786590465-TEST',2,306,313,'mp40',30,30,6,897.6,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (759,1,'1786590465-TEST',2,316,317,'30cal',63,63,4,897.63,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (760,1,'1786590465-TEST',2,306,313,'mp40',30,30,6,897.74,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (761,1,'1786590465-TEST',2,316,317,'30cal',63,63,4,897.85,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (762,1,'1786590465-TEST',2,306,313,'mp40',100,100,1,898.46,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (763,1,'1786590465-TEST',2,305,305,'grenade',26,26,0,902.55,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (764,1,'1786590465-TEST',2,320,316,'luger',12,12,1,917.04,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (765,1,'1786590465-TEST',2,320,309,'luger',30,30,6,919.71,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (766,1,'1786590465-TEST',2,320,309,'luger',30,30,6,919.91,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (767,1,'1786590465-TEST',2,316,320,'30cal',63,63,6,919.99,'2026-08-13 12:33:59','2026-08-13 12:33:59');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (768,1,'1786590465-TEST',2,320,309,'luger',30,30,6,920.13,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (769,1,'1786590465-TEST',2,316,320,'30cal',63,63,6,920.2,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (770,1,'1786590465-TEST',2,309,317,'bar',63,63,6,927.15,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (771,1,'1786590465-TEST',2,309,317,'bar',63,63,6,927.32,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (772,1,'1786590465-TEST',2,309,306,'bar',63,63,4,934.73,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (773,1,'1786590465-TEST',2,305,306,'garand',92,92,2,934.9,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (774,1,'1786590465-TEST',2,305,305,'mortar',5,5,0,938.43,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (775,1,'1786590465-TEST',2,316,316,'mortar',149,100,0,952.75,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (776,1,'1786590465-TEST',2,311,305,'scopedkar',120,100,6,959.44,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (777,1,'1786590465-TEST',2,313,313,'mortar',5,5,0,978.2,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (778,1,'1786590465-TEST',2,320,309,'kar',1,1,4,979.38,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (779,1,'1786590465-TEST',2,320,319,'kar',17,17,4,979.38,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (780,1,'1786590465-TEST',2,306,309,'mp40',30,30,5,982.48,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (781,1,'1786590465-TEST',2,305,306,'garand',90,90,4,991.07,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (782,1,'1786590465-TEST',2,305,306,'garand',11,11,4,991.07,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (783,1,'1786590465-TEST',2,305,317,'garand',120,100,3,994.78,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (784,1,'1786590465-TEST',2,320,305,'kar',120,100,4,996.79,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (785,1,'1786590465-TEST',2,313,304,'spring',120,100,4,998.81,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (786,1,'1786590465-TEST',2,313,314,'spring',120,100,6,1001.79,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (787,1,'1786590465-TEST',2,316,308,'30cal',212,100,1,1002.05,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (788,1,'1786590465-TEST',2,311,313,'scopedkar',400,100,1,1004.32,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (789,1,'1786590465-TEST',2,309,320,'bar',63,63,5,1018.36,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (790,1,'1786590465-TEST',2,309,320,'bar',63,63,5,1018.52,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (791,1,'1786590465-TEST',2,316,304,'30cal',85,85,2,1034.66,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (792,1,'1786590465-TEST',2,316,304,'30cal',63,63,6,1034.88,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (793,1,'1786590465-TEST',2,314,309,'mg34',63,63,4,1036.5,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (794,1,'1786590465-TEST',2,314,309,'mg34',62,62,4,1036.5,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (795,1,'1786590465-TEST',2,306,306,'grenade2',68,68,0,1040.49,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (796,1,'1786590465-TEST',2,305,314,'garand',120,100,2,1040.77,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (797,1,'1786590465-TEST',2,305,305,'grenade',4,4,0,1041.03,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (798,1,'1786590465-TEST',2,305,308,'grenade',16,16,0,1041.03,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (799,1,'1786590465-TEST',2,316,317,'30cal',63,63,4,1042.46,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (800,1,'1786590465-TEST',2,316,317,'30cal',89,89,4,1042.46,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (801,1,'1786590465-TEST',2,305,311,'grenade',39,39,0,1043.13,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (802,1,'1786590465-TEST',2,305,305,'grenade',8,8,0,1043.13,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (803,1,'1786590465-TEST',2,305,308,'grenade',21,21,0,1043.13,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (804,1,'1786590465-TEST',2,305,308,'garand',120,100,3,1044.89,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (805,1,'1786590465-TEST',2,307,320,'greasegun',30,30,5,1062.05,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (806,1,'1786590465-TEST',2,320,307,'mg42',63,63,6,1062.09,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (807,1,'1786590465-TEST',2,320,307,'mg42',63,63,6,1062.26,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (808,1,'1786590465-TEST',2,311,305,'scopedkar',120,100,5,1062.74,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (809,1,'1786590465-TEST',2,306,316,'mp40',30,30,5,1066.02,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (810,1,'1786590465-TEST',2,320,316,'mg42',63,63,7,1066.04,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (811,1,'1786590465-TEST',2,306,316,'mp40',30,30,7,1066.16,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (812,1,'1786590465-TEST',2,311,319,'scopedkar',400,100,1,1073.77,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (813,1,'1786590465-TEST',2,309,320,'bar',63,63,6,1083.98,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (814,1,'1786590465-TEST',2,309,320,'bar',63,63,6,1084.16,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (815,1,'1786590465-TEST',2,307,308,'greasegun',100,100,1,1103.63,'2026-08-13 12:34:00','2026-08-13 12:34:00');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (816,1,'1786590465-TEST',2,307,307,'grenade',39,39,0,1107.14,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (817,1,'1786590465-TEST',2,311,309,'scopedkar',120,100,7,1108.2,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (818,1,'1786590465-TEST',2,314,307,'mg34',212,100,1,1118.8,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (819,1,'1786590465-TEST',2,313,317,'spring',160,100,3,1124.87,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (820,1,'1786590465-TEST',2,320,313,'mp44',37,37,7,1127.5,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (821,1,'1786590465-TEST',2,320,313,'mp44',37,37,7,1127.65,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (822,1,'1786590465-TEST',2,320,313,'mp44',37,37,7,1127.8,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (823,1,'1786590465-TEST',2,319,320,'spring',120,100,7,1128.23,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (824,1,'1786590465-TEST',2,309,306,'bar',85,85,3,1138.48,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (825,1,'1786590465-TEST',2,309,306,'bar',85,85,3,1138.65,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (826,1,'1786590465-TEST',2,308,316,'mp44',37,37,6,1141.52,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (827,1,'1786590465-TEST',2,308,316,'mp44',37,37,6,1141.67,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (828,1,'1786590465-TEST',2,308,316,'mp44',37,37,6,1141.81,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (829,1,'1786590465-TEST',2,307,308,'greasegun',30,30,6,1150.95,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (830,1,'1786590465-TEST',2,307,308,'greasegun',30,30,6,1151.15,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (831,1,'1786590465-TEST',2,308,307,'mp44',37,37,6,1151.98,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (832,1,'1786590465-TEST',2,308,307,'mp44',37,37,6,1152.14,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (833,1,'1786590465-TEST',2,311,307,'scopedkar',160,100,3,1152.6,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (834,1,'1786590465-TEST',2,307,311,'grenade',73,73,0,1155.38,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (835,1,'1786590465-TEST',2,307,308,'grenade',11,11,0,1155.39,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (836,1,'1786590465-TEST',2,308,319,'mp44',37,37,5,1157.08,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (837,1,'1786590465-TEST',2,309,308,'bar',63,63,5,1158.58,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (838,1,'1786590465-TEST',2,319,319,'mortar',34,34,0,1163.33,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (839,1,'1786590465-TEST',2,318,304,'colt',30,30,4,1165.46,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (840,1,'1786590465-TEST',2,318,304,'colt',23,23,4,1165.46,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (841,1,'1786590465-TEST',2,318,304,'colt',30,30,4,1165.69,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (842,1,'1786590465-TEST',2,318,304,'colt',37,37,4,1165.69,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (843,1,'1786590465-TEST',2,319,317,'spring',160,100,2,1168.61,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (844,1,'1786590465-TEST',2,320,319,'kar',120,100,4,1171.29,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (845,1,'1786590465-TEST',2,314,309,'mg34',63,63,7,1173.12,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (846,1,'1786590465-TEST',2,309,314,'bar',63,63,6,1173.29,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (847,1,'1786590465-TEST',2,309,314,'bar',63,63,6,1173.46,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (848,1,'1786590465-TEST',2,320,320,'mortar',12,12,0,1176.11,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (849,1,'1786590465-TEST',2,320,313,'kar',120,100,6,1180.41,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (850,1,'1786590465-TEST',2,316,320,'30cal',212,100,1,1182.53,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (851,1,'1786590465-TEST',2,306,309,'mp40',30,30,4,1183.6,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (852,1,'1786590465-TEST',2,309,306,'bar',212,100,1,1187.75,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (853,1,'1786590465-TEST',2,305,305,'mortar',5,5,0,1189.49,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (854,1,'1786590465-TEST',2,304,309,'kar',120,100,6,1189.78,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (855,1,'1786590465-TEST',2,308,316,'mp44',50,50,2,1212.25,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (856,1,'1786590465-TEST',2,308,316,'mp44',50,50,2,1212.4,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (857,1,'1786590465-TEST',2,320,313,'mp44',37,37,4,1213.5,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (858,1,'1786590465-TEST',2,320,313,'mp44',32,32,4,1213.5,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (859,1,'1786590465-TEST',2,320,313,'mp44',37,37,4,1213.65,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (860,1,'1786590465-TEST',2,307,304,'greasegun',30,30,6,1215.55,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (861,1,'1786590465-TEST',2,307,304,'greasegun',30,30,6,1215.77,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (862,1,'1786590465-TEST',2,307,304,'greasegun',30,30,6,1215.99,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (863,1,'1786590465-TEST',2,307,304,'greasegun',30,30,7,1218.16,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (864,1,'1786590465-TEST',2,314,318,'mg34',63,63,7,1229.36,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (865,1,'1786590465-TEST',2,320,307,'grenade2',4,4,0,1229.46,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (866,1,'1786590465-TEST',2,314,318,'mg34',63,63,7,1229.59,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (867,1,'1786590465-TEST',2,307,307,'mortar',5,5,0,1229.83,'2026-08-13 12:34:01','2026-08-13 12:34:01');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (868,1,'1786590465-TEST',2,307,314,'greasegun',24,24,7,1231.27,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (869,1,'1786590465-TEST',2,317,317,'mortar',112,100,0,1231.34,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (870,1,'1786590465-TEST',2,307,314,'greasegun',24,24,7,1231.49,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (871,1,'1786590465-TEST',2,307,314,'greasegun',24,24,7,1231.71,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (872,1,'1786590465-TEST',2,305,306,'garand',90,90,4,1238.01,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (873,1,'1786590465-TEST',2,305,306,'garand',109,100,4,1238.01,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (874,1,'1786590465-TEST',2,320,307,'mp44',50,50,3,1241.58,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (875,1,'1786590465-TEST',2,320,307,'mp44',37,37,6,1241.72,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (876,1,'1786590465-TEST',2,320,307,'mp44',37,37,6,1241.87,'2026-08-13 12:34:02','2026-08-13 12:34:02');
INSERT INTO `ktp_damage_events` (`id`, `server_id`, `match_id`, `half`, `attacker_id`, `victim_id`, `weapon`, `damage`, `damage_capped`, `hitplace`, `game_time`, `event_time`, `created_at`) VALUES (877,1,'1786590465-TEST',2,306,305,'grenade2',76,76,0,1242.12,'2026-08-13 12:34:02','2026-08-13 12:34:02');
/*!40000 ALTER TABLE `ktp_damage_events` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_flag_positions`
--

DROP TABLE IF EXISTS `ktp_flag_positions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_flag_positions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `server_id` int unsigned NOT NULL,
  `map_name` varchar(32) NOT NULL,
  `flag_index` tinyint NOT NULL,
  `flag_name` varchar(32) NOT NULL,
  `origin_x` mediumint NOT NULL,
  `origin_y` mediumint NOT NULL,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_server_map_flag` (`server_id`,`map_name`,`flag_index`),
  KEY `idx_map` (`map_name`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Static per-flag (x,y) per map, for last-flag-defense / ninja-cap proximity checks';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_flag_positions`
--

LOCK TABLES `ktp_flag_positions` WRITE;
/*!40000 ALTER TABLE `ktp_flag_positions` DISABLE KEYS */;
INSERT INTO `ktp_flag_positions` (`id`, `server_id`, `map_name`, `flag_index`, `flag_name`, `origin_x`, `origin_y`, `updated_at`) VALUES (1,1,'dod_anzio',0,'POINT_ANZIO_LAUNDRY',-1495,-326,'2026-08-13 12:33:54');
INSERT INTO `ktp_flag_positions` (`id`, `server_id`, `map_name`, `flag_index`, `flag_name`, `origin_x`, `origin_y`, `updated_at`) VALUES (2,1,'dod_anzio',1,'POINT_BRIDGE',1040,-288,'2026-08-13 12:33:54');
INSERT INTO `ktp_flag_positions` (`id`, `server_id`, `map_name`, `flag_index`, `flag_name`, `origin_x`, `origin_y`, `updated_at`) VALUES (3,1,'dod_anzio',2,'POINT_ANZIO_STREET',448,800,'2026-08-13 12:33:54');
INSERT INTO `ktp_flag_positions` (`id`, `server_id`, `map_name`, `flag_index`, `flag_name`, `origin_x`, `origin_y`, `updated_at`) VALUES (4,1,'dod_anzio',3,'POINT_ANZIO_PLAZA',-698,923,'2026-08-13 12:33:54');
INSERT INTO `ktp_flag_positions` (`id`, `server_id`, `map_name`, `flag_index`, `flag_name`, `origin_x`, `origin_y`, `updated_at`) VALUES (5,1,'dod_anzio',4,'POINT_ANZIO_HILL',1375,1682,'2026-08-13 12:33:54');
/*!40000 ALTER TABLE `ktp_flag_positions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_match_players`
--

DROP TABLE IF EXISTS `ktp_match_players`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_match_players` (
  `id` int NOT NULL AUTO_INCREMENT,
  `match_id` varchar(64) NOT NULL,
  `player_id` int NOT NULL,
  `steam_id` varchar(32) NOT NULL,
  `player_name` varchar(64) NOT NULL,
  `team` tinyint NOT NULL,
  `joined_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_match_player` (`match_id`,`player_id`),
  KEY `idx_match` (`match_id`),
  KEY `idx_player` (`player_id`),
  KEY `idx_steam` (`steam_id`)
) ENGINE=InnoDB AUTO_INCREMENT=41751 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_match_players`
--

LOCK TABLES `ktp_match_players` WRITE;
/*!40000 ALTER TABLE `ktp_match_players` DISABLE KEYS */;
/*!40000 ALTER TABLE `ktp_match_players` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_match_stats`
--

DROP TABLE IF EXISTS `ktp_match_stats`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_match_stats` (
  `id` int NOT NULL AUTO_INCREMENT,
  `match_id` varchar(64) NOT NULL,
  `player_id` int NOT NULL,
  `half` tinyint NOT NULL DEFAULT '0',
  `kills` int DEFAULT '0',
  `deaths` int DEFAULT '0',
  `headshots` int DEFAULT '0',
  `team_kills` int DEFAULT '0',
  `suicides` int DEFAULT '0',
  `damage` int DEFAULT '0',
  `score` int DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_match_player_half` (`match_id`,`player_id`,`half`),
  KEY `idx_match` (`match_id`),
  KEY `idx_player` (`player_id`)
) ENGINE=InnoDB AUTO_INCREMENT=63207 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_match_stats`
--

LOCK TABLES `ktp_match_stats` WRITE;
/*!40000 ALTER TABLE `ktp_match_stats` DISABLE KEYS */;
/*!40000 ALTER TABLE `ktp_match_stats` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_matches`
--

DROP TABLE IF EXISTS `ktp_matches`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_matches` (
  `id` int NOT NULL AUTO_INCREMENT,
  `match_id` varchar(64) NOT NULL,
  `server_id` int NOT NULL,
  `map_name` varchar(32) NOT NULL,
  `half` tinyint DEFAULT '1',
  `start_time` datetime NOT NULL,
  `end_time` datetime DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_match_id_half` (`match_id`,`half`),
  KEY `idx_server` (`server_id`),
  KEY `idx_start_time` (`start_time`),
  KEY `idx_map` (`map_name`)
) ENGINE=InnoDB AUTO_INCREMENT=3547 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_matches`
--

LOCK TABLES `ktp_matches` WRITE;
/*!40000 ALTER TABLE `ktp_matches` DISABLE KEYS */;
INSERT INTO `ktp_matches` (`id`, `match_id`, `server_id`, `map_name`, `half`, `start_time`, `end_time`, `created_at`) VALUES (3543,'1786590465-TEST',1,'dod_anzio',1,'2026-08-13 12:33:44','2026-08-13 12:33:53','2026-08-13 12:33:44');
INSERT INTO `ktp_matches` (`id`, `match_id`, `server_id`, `map_name`, `half`, `start_time`, `end_time`, `created_at`) VALUES (3545,'1786590465-TEST',1,'dod_anzio',2,'2026-08-13 12:33:54','2026-08-13 12:34:02','2026-08-13 12:33:54');
/*!40000 ALTER TABLE `ktp_matches` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_spike_daily`
--

DROP TABLE IF EXISTS `ktp_spike_daily`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_spike_daily` (
  `day` date NOT NULL,
  `fingerprint` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `server_endpoint` varchar(48) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `phase` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `magnitude_bucket` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `count` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`day`,`fingerprint`,`server_endpoint`),
  KEY `idx_fp` (`fingerprint`),
  KEY `idx_day_bucket` (`day`,`magnitude_bucket`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_spike_daily`
--

LOCK TABLES `ktp_spike_daily` WRITE;
/*!40000 ALTER TABLE `ktp_spike_daily` DISABLE KEYS */;
/*!40000 ALTER TABLE `ktp_spike_daily` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_spike_signatures`
--

DROP TABLE IF EXISTS `ktp_spike_signatures`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_spike_signatures` (
  `fingerprint` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `phase` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `magnitude_bucket` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `first_seen` timestamp NOT NULL,
  `last_seen` timestamp NOT NULL,
  `count` int NOT NULL DEFAULT '0',
  `sample_endpoint` varchar(48) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `sample_line` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `posted_alert` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`fingerprint`),
  KEY `idx_last_seen` (`last_seen`),
  KEY `idx_phase_bucket` (`phase`,`magnitude_bucket`),
  KEY `idx_posted_alert` (`posted_alert`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_spike_signatures`
--

LOCK TABLES `ktp_spike_signatures` WRITE;
/*!40000 ALTER TABLE `ktp_spike_signatures` DISABLE KEYS */;
/*!40000 ALTER TABLE `ktp_spike_signatures` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_telemetry_baselines`
--

DROP TABLE IF EXISTS `ktp_telemetry_baselines`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_telemetry_baselines` (
  `server_endpoint` varchar(48) NOT NULL,
  `day` date NOT NULL,
  `fps_p50_today` float NOT NULL,
  `fps_p50_mean` float DEFAULT NULL,
  `fps_p50_stddev` float DEFAULT NULL,
  `fps_p50_baseline` float DEFAULT NULL,
  `spike_total_today` int NOT NULL,
  `spike_total_mean` float DEFAULT NULL,
  `spike_total_stddev` float DEFAULT NULL,
  `spike_total_baseline` float DEFAULT NULL,
  `warn_fps` tinyint NOT NULL DEFAULT '0',
  `warn_spikes` tinyint NOT NULL DEFAULT '0',
  `posted_to_discord` tinyint NOT NULL DEFAULT '0',
  `computed_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`server_endpoint`,`day`),
  KEY `idx_day` (`day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_telemetry_baselines`
--

LOCK TABLES `ktp_telemetry_baselines` WRITE;
/*!40000 ALTER TABLE `ktp_telemetry_baselines` DISABLE KEYS */;
/*!40000 ALTER TABLE `ktp_telemetry_baselines` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_telemetry_metrics`
--

DROP TABLE IF EXISTS `ktp_telemetry_metrics`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_telemetry_metrics` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `server_endpoint` varchar(48) NOT NULL,
  `recorded_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `window_start` timestamp NULL DEFAULT NULL,
  `window_end` timestamp NULL DEFAULT NULL,
  `fps_p50` float DEFAULT NULL,
  `fps_p95` float DEFAULT NULL,
  `fps_p99` float DEFAULT NULL,
  `fps_stddev` float DEFAULT NULL,
  `fps_min` float DEFAULT NULL,
  `fps_max` float DEFAULT NULL,
  `fps_sample_count` int DEFAULT '0',
  `spike_phys` int NOT NULL DEFAULT '0',
  `spike_read` int NOT NULL DEFAULT '0',
  `spike_steam` int NOT NULL DEFAULT '0',
  `spike_send` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_server_recorded` (`server_endpoint`,`recorded_at`),
  KEY `idx_recorded` (`recorded_at`)
) ENGINE=InnoDB AUTO_INCREMENT=690894 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Phase 8.2: per-cycle FPS/spike aggregates from KTP_PROFILE/KTP_SPIKE log lines';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_telemetry_metrics`
--

LOCK TABLES `ktp_telemetry_metrics` WRITE;
/*!40000 ALTER TABLE `ktp_telemetry_metrics` DISABLE KEYS */;
/*!40000 ALTER TABLE `ktp_telemetry_metrics` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `ktp_telemetry_watermarks`
--

DROP TABLE IF EXISTS `ktp_telemetry_watermarks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ktp_telemetry_watermarks` (
  `server_endpoint` varchar(48) NOT NULL,
  `last_seen_ts` timestamp NULL DEFAULT NULL,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`server_endpoint`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Phase 8.2: per-server last-parsed log timestamp (dedup across cycles)';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `ktp_telemetry_watermarks`
--

LOCK TABLES `ktp_telemetry_watermarks` WRITE;
/*!40000 ALTER TABLE `ktp_telemetry_watermarks` DISABLE KEYS */;
/*!40000 ALTER TABLE `ktp_telemetry_watermarks` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `support_reports`
--

DROP TABLE IF EXISTS `support_reports`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `support_reports` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `intake_id` char(12) NOT NULL,
  `category` varchar(32) NOT NULL,
  `channel` varchar(16) NOT NULL,
  `server_label` varchar(32) DEFAULT NULL,
  `body` varchar(2000) NOT NULL,
  `handle` varchar(64) DEFAULT NULL,
  `ip_hash` char(32) NOT NULL,
  `relayed` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_support_reports_intake` (`intake_id`),
  KEY `ix_support_reports_created` (`created_at`),
  KEY `ix_support_reports_unrelayed` (`relayed`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `support_reports`
--

LOCK TABLES `support_reports` WRITE;
/*!40000 ALTER TABLE `support_reports` DISABLE KEYS */;
/*!40000 ALTER TABLE `support_reports` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `support_schema_migrations`
--

DROP TABLE IF EXISTS `support_schema_migrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `support_schema_migrations` (
  `version` varchar(64) NOT NULL,
  `applied_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `support_schema_migrations`
--

LOCK TABLES `support_schema_migrations` WRITE;
/*!40000 ALTER TABLE `support_schema_migrations` DISABLE KEYS */;
/*!40000 ALTER TABLE `support_schema_migrations` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `support_tickets`
--

DROP TABLE IF EXISTS `support_tickets`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `support_tickets` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `level` varchar(8) NOT NULL DEFAULT 'cl',
  `group_name` varchar(32) NOT NULL DEFAULT 'ktp_admin',
  `steam_id` varchar(32) NOT NULL,
  `display_name` varchar(64) NOT NULL,
  `requested_by` varchar(32) NOT NULL,
  `requested_note` varchar(500) DEFAULT NULL,
  `status` varchar(16) NOT NULL DEFAULT 'submitted',
  `season` smallint unsigned DEFAULT NULL,
  `decided_by` varchar(32) DEFAULT NULL,
  `applied_by` varchar(32) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_support_tickets_status` (`status`),
  KEY `ix_support_tickets_expiry` (`group_name`,`status`,`season`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `support_tickets`
--

LOCK TABLES `support_tickets` WRITE;
/*!40000 ALTER TABLE `support_tickets` DISABLE KEYS */;
/*!40000 ALTER TABLE `support_tickets` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-08-13 12:34:06
